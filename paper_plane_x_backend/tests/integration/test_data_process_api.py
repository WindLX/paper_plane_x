"""Data-process API tests."""

import asyncio
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.data_process_tasks.lifecycle import (
    get_data_process_task_manager,
)
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessQueueTask,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.orchestrators.data_process import (
    DataProcessOrchestrator,
)


def _stub_enqueue_state(task: DataProcessQueueTask) -> DataProcessTaskState:
    state = DataProcessTaskState(
        task_id=task.task_id,
        paper_id=task.paper_id,
        payload=task.payload,
        status=DataProcessTaskStatus.QUEUED,
        created_at=datetime.now(),
        retry_of_task_id=task.retry_of_task_id,
    )
    get_data_process_task_manager().task_states[task.task_id] = state
    return state


def _insert_linked_paper(
    db: Database, project_id: str, payload: dict[str, object]
) -> None:
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


class TestDataProcessAPI:
    """Data-process API 测试类。"""

    def test_start_data_process_queues_task(
        self,
        client: TestClient,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """测试上传单篇 PDF 会创建待处理记录并入队。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Data Process Test Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        saved_paths: list[Path] = []
        queued_tasks: list[DataProcessQueueTask] = []

        async def fake_save_upload_file(self, upload_file, paper_id: str) -> Path:
            output = tmp_path / f"{paper_id}.pdf"
            output.write_bytes(b"%PDF-1.4 fake")
            saved_paths.append(output)
            return output

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            state = _stub_enqueue_state(task)
            queued_tasks.append(task)
            return state

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        response = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
            data={
                "title": "Queued Paper",
                "authors": "Alice, Bob",
                "year": "2024",
                "publication": "ICML",
            },
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["status"] == "QUEUED"
        assert payload["task_id"]
        assert payload["resource_type"] == "paper"
        assert payload["resource_id"]

        paper_id = payload["resource_id"]
        assert len(saved_paths) == 1
        assert len(queued_tasks) == 1
        assert queued_tasks[0].paper_id == paper_id
        assert queued_tasks[0].payload["pdf_path"] == str(saved_paths[0])

        paper_detail = client.get(f"/api/v1/papers/{paper_id}")
        assert paper_detail.status_code == 200
        detail_payload = paper_detail.json()
        assert detail_payload["title"] == "Queued Paper"
        assert detail_payload["authors"] == ["Alice", "Bob"]
        assert detail_payload["year"] == 2024
        assert detail_payload["publication"] == "ICML"
        assert detail_payload["extraction_status"] == "PENDING"
        assert detail_payload["raw_pdf_path"] == str(saved_paths[0])

        paper_row = db.fetchone(
            "SELECT paper_id, raw_pdf_sha256 FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        assert paper_row is not None
        assert paper_row["raw_pdf_sha256"] is not None

    def test_start_data_process_without_project_context(
        self, client: TestClient
    ) -> None:
        """测试不传 project 上下文时仍可正常入队。"""
        response = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 202

    def test_start_data_process_rejects_invalid_custom_meta(
        self, client: TestClient
    ) -> None:
        """测试创建论文时非法 custom_meta 会被 422 拒绝。"""
        response = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
            data={"custom_meta": '{"broken": }'},
        )

        assert response.status_code == 422
        assert "custom_meta" in response.json()["detail"]

    @pytest.mark.parametrize("custom_meta", ["[]", '"text"', "123", "true", "null"])
    def test_start_data_process_rejects_non_object_custom_meta(
        self, client: TestClient, custom_meta: str
    ) -> None:
        """测试创建论文时 custom_meta 为合法 JSON 但非 object 也会被 422 拒绝。"""
        response = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
            data={"custom_meta": custom_meta},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "custom_meta must be a JSON object"

    def test_start_data_process_returns_500_when_enqueue_fails(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """测试入队失败时返回 500。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Data Process Error Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_save_upload_file(self, upload_file, paper_id: str) -> Path:
            output = tmp_path / f"{paper_id}.pdf"
            output.write_bytes(b"%PDF-1.4 fake")
            return output

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        response = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 500
        assert "Internal error" in response.json()["detail"]

    def test_retry_data_process_queues_task(
        self,
        client: TestClient,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """测试同 paper_id 重传并重试会入队并重置状态。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Retry Data Process Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-retry-1",
                "title": "Old Title",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2023,
                "publication": "Old Venue",
                "doi": "old-doi",
                "md_content": "old markdown",
                "images_paths": json.dumps(["old.png"], ensure_ascii=False),
                "extraction_status": "FAILED",
                "quick_scan": json.dumps({"old": True}, ensure_ascii=False),
                "synthesis_data": json.dumps({"old": True}, ensure_ascii=False),
                "extraction_fact_check_status": "FAILED",
                "extraction_fact_check_result": json.dumps(
                    {"error": "old"}, ensure_ascii=False
                ),
                "extraction_retry_count": 2,
                "analysis_retry_count": 1,
                "created_at": now,
                "updated_at": now,
            },
        )

        saved_paths: list[Path] = []
        queued_tasks: list[DataProcessQueueTask] = []

        async def fake_save_upload_file(self, upload_file, paper_id: str) -> Path:
            output = tmp_path / f"{paper_id}.pdf"
            output.write_bytes(b"%PDF-1.4 retry")
            saved_paths.append(output)
            return output

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            state = _stub_enqueue_state(task)
            queued_tasks.append(task)
            return state

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        response = client.post(
            "/api/v1/papers/paper-retry-1/reprocess",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["resource_id"] == "paper-retry-1"
        assert payload["status"] == "QUEUED"
        assert payload["task_id"]

        assert len(saved_paths) == 1
        assert len(queued_tasks) == 1
        assert queued_tasks[0].paper_id == "paper-retry-1"
        assert queued_tasks[0].payload["pdf_path"] == str(saved_paths[0])

        row = db.fetchone(
            "SELECT * FROM papers WHERE paper_id = ?",
            ("paper-retry-1",),
        )
        assert row is not None
        assert row["title"] == "Old Title"
        assert row["md_content"] == ""
        assert json.loads(row["authors"]) == ["Alice"]
        assert row["year"] == 2023
        assert json.loads(row["images_paths"]) == []
        assert row["quick_scan"] is None
        assert row["synthesis_data"] is None
        assert row["extraction_fact_check_result"] is None
        assert row["analysis_fact_check_result"] is None
        assert row["extraction_status"] == "PENDING"
        assert row["extraction_fact_check_status"] == "PENDING"
        assert row["analysis_fact_check_status"] == "PENDING"
        assert row["raw_pdf_path"] == str(saved_paths[0])
        assert row["raw_pdf_sha256"] is not None

    def test_retry_data_process_paper_not_found(self, client: TestClient) -> None:
        """测试重试不存在的 paper 返回 404。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Retry 404 Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        response = client.post(
            "/api/v1/papers/not-found/reprocess",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 404

    def test_retry_data_process_conflict_when_processing(
        self, client: TestClient, db: Database
    ) -> None:
        """测试处理中 paper 不可重试。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Retry Conflict Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-processing",
                "title": "Processing",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PROCESSING",
                "extraction_fact_check_status": "PENDING",
                "extraction_retry_count": 0,
                "analysis_retry_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            "/api/v1/papers/paper-processing/reprocess",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 409

    def test_manual_update_data_process_result_success(
        self, client: TestClient, db: Database
    ) -> None:
        """测试人工更新元数据与结果字段。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Manual Update Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-manual-1",
                "title": "Before",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2022,
                "publication": "Old Venue",
                "doi": "old-doi",
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            "/api/v1/papers/paper-manual-1",
            json={
                "title": "After",
                "authors": ["Tom", "Jerry"],
                "year": 2026,
                "publication": "NeurIPS",
                "doi": "10.1/manual",
                "custom_meta": '{"labels":["survey","manual"]}',
                "extraction_status": "HUMAN_COMPLETED",
                "quick_scan": {"manual": True},
                "synthesis_data": {"sections": 3},
                "extraction_fact_check_status": "HUMAN_PASSED",
                "extraction_fact_check_result": {"reviewer": "human"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["paper_id"] == "paper-manual-1"
        assert payload["title"] == "After"
        assert payload["authors"] == ["Tom", "Jerry"]
        assert payload["year"] == 2026
        assert payload["publication"] == "NeurIPS"
        assert payload["custom_meta"] == '{"labels":["survey","manual"]}'
        assert payload["extraction_status"] == "HUMAN_COMPLETED"
        assert payload["extraction_fact_check_status"] == "HUMAN_PASSED"
        assert payload["quick_scan"] == {"manual": True}
        assert payload["synthesis_data"] == {"sections": 3}
        assert payload["extraction_fact_check_result"] == {"reviewer": "human"}

        row = db.fetchone(
            "SELECT * FROM papers WHERE paper_id = ?",
            ("paper-manual-1",),
        )
        assert row is not None
        assert row["title"] == "After"
        assert json.loads(row["authors"]) == ["Tom", "Jerry"]
        assert row["publication"] == "NeurIPS"
        assert row["custom_meta"] == '{"labels":["survey","manual"]}'
        assert row["extraction_status"] == "HUMAN_COMPLETED"
        assert row["extraction_fact_check_status"] == "HUMAN_PASSED"

    def test_manual_update_data_process_result_accepts_failed_status(
        self, client: TestClient, db: Database
    ) -> None:
        """测试人工更新接口允许设置 FAILED 状态。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Manual Update Failed Status Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-manual-failed",
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PENDING",
                "extraction_fact_check_status": "PENDING",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            "/api/v1/papers/paper-manual-failed",
            json={
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "extraction_fact_check_result": {"error": "manual fail"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["extraction_status"] == "FAILED"
        assert payload["extraction_fact_check_status"] == "FAILED"
        assert payload["extraction_fact_check_result"] == {"error": "manual fail"}

    def test_manual_update_data_process_result_rejects_non_human_or_failed_status(
        self, client: TestClient, db: Database
    ) -> None:
        """测试人工更新接口拒绝非 HUMAN_* / FAILED 状态。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Manual Update Validate Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-manual-2",
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            "/api/v1/papers/paper-manual-2",
            json={
                "extraction_status": "COMPLETED",
                "extraction_fact_check_status": "PASSED",
            },
        )
        assert response.status_code == 422

    def test_manual_update_rejects_invalid_custom_meta(
        self, client: TestClient, db: Database
    ) -> None:
        """测试手动更新时非法 custom_meta 会被 422 拒绝。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Manual Update Invalid Custom Meta Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-manual-bad-meta",
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            "/api/v1/papers/paper-manual-bad-meta",
            json={"custom_meta": '{"broken": }'},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize("custom_meta", ["[]", '"text"', "123", "true", "null"])
    def test_manual_update_rejects_non_object_custom_meta(
        self, client: TestClient, db: Database, custom_meta: str
    ) -> None:
        """测试手动更新时 custom_meta 为合法 JSON 但非 object 也会被 422 拒绝。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Manual Update Non Object Custom Meta Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        now = datetime.now()
        _insert_linked_paper(
            db,
            project_id,
            {
                "paper_id": "paper-manual-non-object-meta",
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "extraction_fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            "/api/v1/papers/paper-manual-non-object-meta",
            json={"custom_meta": custom_meta},
        )

        assert response.status_code == 422
        details = response.json()["detail"]
        assert isinstance(details, list)
        assert any(
            "custom_meta" in ".".join(str(part) for part in item.get("loc", []))
            and "JSON object" in str(item.get("msg", ""))
            for item in details
        )

    def test_list_data_process_tasks(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试任务列表接口返回队列统计与任务详情。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task List Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        create_task_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert create_task_resp.status_code == 202

        list_resp = client.get("/api/v1/data-process/tasks")
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["queued"] >= 1
        assert len(payload["items"]) >= 1
        assert payload["items"][0]["status"] in {"QUEUED", "RUNNING", "COMPLETED"}

    def test_cancel_data_process_task(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试取消排队任务。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task Cancel Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        create_task_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert create_task_resp.status_code == 202
        task_id = create_task_resp.json()["task_id"]

        cancel_resp = client.post(f"/api/v1/data-process/tasks/{task_id}/cancel")
        assert cancel_resp.status_code == 200
        cancel_payload = cancel_resp.json()
        assert cancel_payload["task_id"] == task_id
        assert cancel_payload["status"] == "CANCELED"

    def test_retry_failed_task(
        self,
        client: TestClient,
        db: Database,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试重试失败任务会创建新任务。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task Retry Failed Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        paper_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert paper_resp.status_code == 202
        original_task_id = paper_resp.json()["task_id"]
        paper_id = paper_resp.json()["resource_id"]

        # 手工模拟任务失败状态
        task_state = get_data_process_task_manager().task_states[original_task_id]
        task_state.status = DataProcessTaskStatus.FAILED
        task_state.error = "mock failed"
        task_state.finished_at = datetime.now()
        get_data_process_task_manager().task_states[original_task_id] = task_state

        raw_pdf_path_row = db.fetchone(
            "SELECT raw_pdf_path FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        assert raw_pdf_path_row is not None
        assert raw_pdf_path_row["raw_pdf_path"]

        retry_resp = client.post(f"/api/v1/data-process/tasks/{original_task_id}/retry")
        assert retry_resp.status_code == 202
        retry_payload = retry_resp.json()
        assert retry_payload["paper_id"] == paper_id
        assert retry_payload["task_id"]
        assert retry_payload["task_id"] != original_task_id

    def test_retry_failed_task_conflict_when_task_not_failed(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试非失败任务重试返回 409。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task Retry Conflict Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        task_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert task_resp.status_code == 202
        task_id = task_resp.json()["task_id"]

        retry_resp = client.post(f"/api/v1/data-process/tasks/{task_id}/retry")
        assert retry_resp.status_code == 409

    def test_retry_canceled_task(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """测试已取消任务可通过 retry 重新入队。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task Retry Canceled Project"},
        )
        assert create_project_resp.status_code == 201
        _ = create_project_resp.json()["project_id"]

        async def fake_save_upload_file(self, upload_file, paper_id: str) -> Path:
            output = tmp_path / f"{paper_id}.pdf"
            output.write_bytes(b"%PDF-1.4 retry-canceled")
            return output

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(
            DataProcessOrchestrator, "_save_upload_file", fake_save_upload_file
        )
        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        start_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert start_resp.status_code == 202
        original_task_id = start_resp.json()["task_id"]
        paper_id = start_resp.json()["resource_id"]

        cancel_resp = client.post(
            f"/api/v1/data-process/tasks/{original_task_id}/cancel"
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELED"

        retry_resp = client.post(f"/api/v1/data-process/tasks/{original_task_id}/retry")
        assert retry_resp.status_code == 202
        payload = retry_resp.json()
        assert payload["paper_id"] == paper_id
        assert payload["task_id"] != original_task_id

    def test_shutdown_with_running_task_does_not_hang(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试存在运行中任务时，关闭应用不会卡住。"""
        manager = get_data_process_task_manager()
        manager._shutdown_timeout = 0.1

        started = threading.Event()

        async def fake_run(self, task):  # type: ignore[no-untyped-def]
            _ = task
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await asyncio.sleep(0.5)
                raise

        monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

        create_task_resp = client.post(
            "/api/v1/papers",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert create_task_resp.status_code == 202
        assert started.wait(timeout=1.0)

        begin = time.monotonic()
        client.close()
        elapsed = time.monotonic() - begin

        assert elapsed < 0.8
