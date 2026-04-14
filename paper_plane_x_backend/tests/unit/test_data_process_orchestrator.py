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
from paper_plane_x_backend.services.data_process_orchestrator import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)
from paper_plane_x_backend.services.data_process_task_manager import (
    DataProcessTaskManager,
    DataProcessTaskState,
)


@pytest.fixture
def orchestrator(db):
    manager = DataProcessTaskManager(worker_count=1)
    return DataProcessOrchestrator(db=db, task_manager=manager)


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


class TestDataProcessOrchestrator:
    def test_build_metadata_splits_authors(self, orchestrator: DataProcessOrchestrator):
        metadata = orchestrator.build_metadata(
            title="T",
            authors="Alice, Bob,  ",
            year=2025,
            venue=None,
            doi=None,
        )
        assert metadata == {
            "title": "T",
            "authors": ["Alice", "Bob"],
            "year": 2025,
        }

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_raw_pdf_path(
        self, orchestrator: DataProcessOrchestrator, db
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-1"
        now = datetime.now()
        db.insert(
            "papers",
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "raw_pdf_path": None,
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-1"] = DataProcessTaskState(
            task_id="task-1",
            project_id=project_id,
            payload={"paper_id": paper_id},
            status=DataProcessTaskStatus.FAILED,
            created_at=now,
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(
                project_id=project_id, task_id="task-1"
            )

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

        db.insert(
            "papers",
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "raw_pdf_path": str(pdf_path),
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-old"] = DataProcessTaskState(
            task_id="task-old",
            project_id=project_id,
            payload={"paper_id": paper_id, "pdf_path": str(pdf_path)},
            status=DataProcessTaskStatus.FAILED,
            created_at=now,
        )

        captured = {}

        async def fake_submit(self, task):
            captured["task"] = task
            return DataProcessTaskState(
                task_id="task-new",
                project_id=task.project_id,
                payload=task.payload,
                status=DataProcessTaskStatus.QUEUED,
                created_at=datetime.now(),
                retry_of_task_id=task.retry_of_task_id,
            )

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit)

        new_state, resource_paper_id = await orchestrator.retry_failed_task(
            project_id=project_id,
            task_id="task-old",
        )

        assert resource_paper_id == paper_id
        assert new_state.task_id == "task-new"
        assert captured["task"].retry_of_task_id == "task-old"
        assert captured["task"].payload["paper_id"] == paper_id
        assert captured["task"].payload["pdf_path"] == str(pdf_path)

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_paper_id_in_payload(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
    ) -> None:
        project_id = _insert_project(db)
        now = datetime.now()

        orchestrator.task_manager.task_states["task-missing-paper-id"] = (
            DataProcessTaskState(
                task_id="task-missing-paper-id",
                project_id=project_id,
                payload={},
                status=DataProcessTaskStatus.FAILED,
                created_at=now,
            )
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(
                project_id=project_id,
                task_id="task-missing-paper-id",
            )

        assert exc.value.status_code == 400
        assert "paper_id" in exc.value.detail

    @pytest.mark.asyncio
    async def test_retry_failed_task_requires_existing_raw_pdf_file(
        self,
        orchestrator: DataProcessOrchestrator,
        db,
    ) -> None:
        project_id = _insert_project(db)
        paper_id = "paper-missing-file"
        now = datetime.now()

        db.insert(
            "papers",
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "raw_pdf_path": "/tmp/definitely-not-exists-paper-plane-x.pdf",
                "created_at": now,
                "updated_at": now,
            },
        )

        orchestrator.task_manager.task_states["task-missing-file"] = (
            DataProcessTaskState(
                task_id="task-missing-file",
                project_id=project_id,
                payload={"paper_id": paper_id},
                status=DataProcessTaskStatus.FAILED,
                created_at=now,
            )
        )

        with pytest.raises(DataProcessDomainError) as exc:
            await orchestrator.retry_failed_task(
                project_id=project_id,
                task_id="task-missing-file",
            )

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

        db.insert(
            "papers",
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": "x",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "# already parsed",
                "raw_pdf_path": "/tmp/old.pdf",
                "raw_pdf_sha256": pdf_hash,
                "images_paths": json.dumps(["/tmp/old.png"], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
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
                project_id=task.project_id,
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
        ) -> None:
            captured["paper_id"] = paper_id
            captured["raw_pdf_sha256"] = raw_pdf_sha256
            captured["preserve_parse_result"] = preserve_parse_result

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit)
        monkeypatch.setattr(
            orchestrator.paper_service,
            "reset_paper_for_retry",
            fake_reset_paper_for_retry,
        )

        task_state = await orchestrator.retry_upload(
            project_id=project_id,
            paper_id=paper_id,
            upload_file=UploadFile(filename="same.pdf", file=io.BytesIO(pdf_bytes)),
        )

        assert task_state.task_id == "task-new"
        assert captured["paper_id"] == paper_id
        assert captured["raw_pdf_sha256"] == pdf_hash
        assert captured["preserve_parse_result"] is True

    def test_manual_update_paper_success(
        self, orchestrator: DataProcessOrchestrator, db
    ):
        project_id = _insert_project(db)
        paper_id = "paper-manual"
        now = datetime.now()

        db.insert(
            "papers",
            {
                "paper_id": paper_id,
                "project_id": project_id,
                "title": "old",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        paper = orchestrator.manual_update_paper(
            project_id=project_id,
            paper_id=paper_id,
            title="new",
            extraction_status=ExtractionStatus.HUMAN_COMPLETED,
            fact_check_status=FactCheckStatus.HUMAN_PASSED,
            quick_scan={"manual": True},
            synthesis_data={"ok": True},
            fact_check_result={"note": "reviewed"},
        )

        assert paper.title == "new"
        assert paper.extraction_status.value == "HUMAN_COMPLETED"
        assert paper.fact_check_status.value == "HUMAN_PASSED"
