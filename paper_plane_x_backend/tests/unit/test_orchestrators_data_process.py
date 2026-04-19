"""Data-process orchestrator tests."""

import io
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi import UploadFile

from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    ExtractionStatus,
    FactCheckStatus,
    Project,
)
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.orchestrators.data_process import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)


@pytest.fixture
def orchestrator(db):
    manager = DataProcessTaskManager(worker_count=1)
    return DataProcessOrchestrator(
        db=db,
        task_manager=manager,
    )


def _insert_project(db, project_id: str = "proj-1") -> str:
    now = datetime.now()
    project = Project(
        project_id=project_id,
        name="orchestrator-test",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())
    return project_id


def _insert_linked_paper(db, project_id: str, payload: dict[str, object]) -> None:
    data = dict(payload)
    paper_id = data["paper_id"]
    db.insert("papers", data)
    db.execute(
        """
        INSERT INTO paper_projects (paper_id, project_id)
        VALUES (?, ?)
        """,
        (paper_id, project_id),
    )


class TestDataProcessOrchestrator:
    def test_build_metadata_splits_authors(self, orchestrator: DataProcessOrchestrator):
        metadata = orchestrator.build_metadata(
            title="T",
            authors="Alice, Bob,  ",
            year=2025,
            publication=None,
            doi=None,
            custom_meta=None,
        )
        assert metadata == {
            "title": "T",
            "authors": ["Alice", "Bob"],
            "year": 2025,
        }

    def test_reset_paper_for_retry_clears_fields(
        self,
        orchestrator: DataProcessOrchestrator,
    ) -> None:
        paper = orchestrator.paper_repo.create(
            md_content="# MD",
            extraction_status=ExtractionStatus.COMPLETED,
        )
        orchestrator.paper_repo.update(
            paper.paper_id,
            {
                "quick_scan": '{"ok": true}',
                "synthesis_data": '{"summary": "x"}',
                "extraction_fact_check_result": '{"passed": true}',
                "analysis_fact_check_result": '{"passed": true}',
                "extraction_retry_count": 2,
                "analysis_retry_count": 1,
            },
        )

        old_paper = orchestrator._reset_paper_for_retry(paper_id=paper.paper_id)
        assert old_paper.paper_id == paper.paper_id

        updated = orchestrator.paper_repo.get(paper.paper_id)
        assert updated is not None
        assert updated.extraction_status.value == "PENDING"
        assert updated.extraction_fact_check_status.value == "PENDING"
        assert updated.analysis_fact_check_status.value == "PENDING"
        assert updated.quick_scan is None
        assert updated.synthesis_data is None
        assert updated.extraction_fact_check_result is None
        assert updated.analysis_fact_check_result is None
        assert updated.extraction_retry_count == 0
        assert updated.analysis_retry_count == 0
        assert updated.md_content == ""
        assert updated.images_paths == []

    def test_reset_paper_for_retry_preserves_parse_result_when_asked(
        self,
        orchestrator: DataProcessOrchestrator,
    ) -> None:
        paper = orchestrator.paper_repo.create(
            md_content="# MD",
            images_paths=["/a.png"],
            extraction_status=ExtractionStatus.FAILED,
        )

        orchestrator._reset_paper_for_retry(
            paper_id=paper.paper_id,
            preserve_parse_result=True,
        )

        updated = orchestrator.paper_repo.get(paper.paper_id)
        assert updated is not None
        assert updated.md_content == "# MD"
        assert updated.images_paths == ["/a.png"]

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_raw_pdf_path(
        self, orchestrator: DataProcessOrchestrator, db
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-1"
        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": paper_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "raw_pdf_path": None,
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-1"] = DataProcessTaskState(
            task_id="task-1",
            paper_id=paper_id,
            payload={"paper_id": paper_id},
            status=DataProcessTaskStatus.FAILED,
            created_at=now,
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(task_id="task-1")

        assert exc.value.status_code == 400
        assert "raw_pdf_path" in exc.value.detail

    @pytest.mark.asyncio
    async def test_retry_failed_task_queues_new_task(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-2"
        now = datetime.now()
        pdf_path = tmp_path / "paper-2.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": paper_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "raw_pdf_path": str(pdf_path),
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-old"] = DataProcessTaskState(
            task_id="task-old",
            paper_id=paper_id,
            payload={"paper_id": paper_id, "pdf_path": str(pdf_path)},
            status=DataProcessTaskStatus.FAILED,
            created_at=now,
        )

        captured = {}

        async def fake_submit(self, task):
            captured["task"] = task
            return DataProcessTaskState(
                task_id="task-new",
                paper_id=task.paper_id,
                payload=task.payload,
                status=DataProcessTaskStatus.QUEUED,
                created_at=datetime.now(),
                retry_of_task_id=task.retry_of_task_id,
            )

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit)

        new_state, resource_paper_id = await orchestrator.retry_failed_task(
            task_id="task-old",
        )

        assert resource_paper_id == paper_id
        assert new_state.task_id == "task-new"
        assert captured["task"].retry_of_task_id == "task-old"
        assert captured["task"].paper_id == paper_id
        assert captured["task"].payload["pdf_path"] == str(pdf_path)

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_existing_paper(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
    ) -> None:
        _insert_project(db)
        now = datetime.now()

        orchestrator.task_manager.task_states["task-missing-paper-id"] = (
            DataProcessTaskState(
                task_id="task-missing-paper-id",
                paper_id="",
                payload={},
                status=DataProcessTaskStatus.FAILED,
                created_at=now,
            )
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(task_id="task-missing-paper-id")

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_existing_raw_pdf_file(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-missing-file"
        now = datetime.now()

        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": paper_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "raw_pdf_path": "/tmp/definitely-not-exists-paper-plane-x.pdf",
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-missing-file"] = (
            DataProcessTaskState(
                task_id="task-missing-file",
                paper_id=paper_id,
                payload={"paper_id": paper_id},
                status=DataProcessTaskStatus.FAILED,
                created_at=now,
            )
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(task_id="task-missing-file")

        assert exc.value.status_code == 400
        assert "Raw PDF file not found" in exc.value.detail

    @pytest.mark.asyncio
    async def test_retry_upload_same_pdf_hash_preserves_parse_result(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-same-hash"
        now = datetime.now()
        pdf_bytes = b"%PDF-1.4 same-content"
        pdf_hash = sha256(pdf_bytes).hexdigest()

        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": paper_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "# already parsed",
                "raw_pdf_path": "/tmp/old.pdf",
                "raw_pdf_sha256": pdf_hash,
                "images_paths": json.dumps(["/tmp/old.png"], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        captured: dict[str, object] = {}

        async def fake_save_upload_file(self, upload_file, paper_id_arg: str) -> Path:
            path = tmp_path / f"{paper_id_arg}.pdf"
            path.write_bytes(pdf_bytes)
            return path

        async def fake_submit(self, task):
            return DataProcessTaskState(
                task_id="task-new",
                paper_id=task.paper_id,
                payload=task.payload,
                status=DataProcessTaskStatus.QUEUED,
                created_at=datetime.now(),
            )

        def fake_reset_paper_for_retry(
            *,
            paper_id: str,
            raw_pdf_path: str | None,
            raw_pdf_sha256: str | None,
            preserve_parse_result: bool,
        ):
            captured["paper_id"] = paper_id
            captured["raw_pdf_sha256"] = raw_pdf_sha256
            captured["preserve_parse_result"] = preserve_parse_result
            return orchestrator.paper_repo.get(paper_id)

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit)
        monkeypatch.setattr(
            orchestrator,
            "_reset_paper_for_retry",
            fake_reset_paper_for_retry,
        )

        task_state = await orchestrator.retry_upload(
            paper_id=paper_id,
            upload_file=UploadFile(filename="same.pdf", file=io.BytesIO(pdf_bytes)),
        )

        assert task_state.task_id == "task-new"
        assert captured["paper_id"] == paper_id
        assert captured["raw_pdf_sha256"] == pdf_hash
        assert captured["preserve_parse_result"] is True

    def test_update_paper_success(self, orchestrator: DataProcessOrchestrator, db):
        project_id = _insert_project(db)
        paper_id = "paper-manual"
        now = datetime.now()

        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": paper_id,
                "title": "old",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        paper = orchestrator.update_paper(
            paper_id=paper_id,
            title="new",
            extraction_status=ExtractionStatus.HUMAN_COMPLETED,
            extraction_fact_check_status=FactCheckStatus.HUMAN_PASSED,
            quick_scan={"manual": True},
            synthesis_data={"ok": True},
            extraction_fact_check_result={"note": "reviewed"},
        )

        assert paper.title == "new"
        assert paper.extraction_status.value == "HUMAN_COMPLETED"
        assert paper.extraction_fact_check_status.value == "HUMAN_PASSED"

    @pytest.mark.asyncio
    async def test_start_reuses_parse_result_from_other_project_by_hash(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        source_project_id = _insert_project(db, project_id="proj-source")
        now = datetime.now()
        pdf_bytes = b"%PDF-1.4 cross-project reuse"
        pdf_hash = sha256(pdf_bytes).hexdigest()

        _insert_linked_paper(
            db,
            source_project_id,
            {
                "paper_id": "paper-source",
                "title": "source",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "md_content": "# parsed from source",
                "images_paths": json.dumps(["/tmp/source.png"], ensure_ascii=False),
                "raw_pdf_path": "/tmp/source.pdf",
                "raw_pdf_sha256": pdf_hash,
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        async def fake_save_upload_file(self, upload_file, paper_id_arg: str) -> Path:
            path = tmp_path / f"{paper_id_arg}.pdf"
            path.write_bytes(pdf_bytes)
            return path

        async def fake_submit(self, task):
            return DataProcessTaskState(
                task_id="task-reuse",
                paper_id=task.paper_id,
                payload=task.payload,
                status=DataProcessTaskStatus.QUEUED,
                created_at=datetime.now(),
            )

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit)

        task_state, new_paper_id = await orchestrator.start(
            upload_file=UploadFile(filename="reuse.pdf", file=io.BytesIO(pdf_bytes)),
            metadata={},
        )

        assert task_state.task_id == "task-reuse"
        new_paper_row = db.fetchone(
            "SELECT md_content, images_paths FROM papers WHERE paper_id = ?",
            (new_paper_id,),
        )
        assert new_paper_row is not None
        assert new_paper_row["md_content"] == "# parsed from source"
        assert json.loads(new_paper_row["images_paths"]) == ["/tmp/source.png"]
        link_rows = db.fetchall(
            "SELECT project_id FROM paper_projects WHERE paper_id = ? ORDER BY project_id",
            ("paper-source",),
        )
        linked_project_ids = [row["project_id"] for row in link_rows]
        assert source_project_id in linked_project_ids
