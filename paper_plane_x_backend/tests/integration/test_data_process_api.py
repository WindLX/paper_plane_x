"""Data-process API tests."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.routers import data_process as data_process_router
from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services import Database
from paper_plane_x_backend.services.data_process_orchestrator import (
    DataProcessOrchestrator,
)
from paper_plane_x_backend.services.data_process_task_manager import (
    DataProcessQueueTask,
    DataProcessTaskState,
)


def _stub_enqueue_state(task: DataProcessQueueTask) -> DataProcessTaskState:
    state = DataProcessTaskState(
        task_id=task.task_id,
        project_id=task.project_id,
        payload=task.payload,
        status=DataProcessTaskStatus.QUEUED,
        created_at=datetime.now(),
        retry_of_task_id=task.retry_of_task_id,
    )
    data_process_router._task_manager.task_states[task.task_id] = state
    return state


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
        project_id = create_project_resp.json()["project_id"]

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
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
            data={
                "title": "Queued Paper",
                "authors": "Alice, Bob",
                "year": "2024",
                "venue": "ICML",
            },
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["project_id"] == project_id
        assert payload["status"] == "QUEUED"
        assert payload["task_id"]
        assert payload["resource_type"] == "paper"
        assert payload["resource_id"]

        paper_id = payload["resource_id"]
        assert len(saved_paths) == 1
        assert len(queued_tasks) == 1
        assert queued_tasks[0].payload["paper_id"] == paper_id
        assert queued_tasks[0].payload["pdf_path"] == str(saved_paths[0])

        paper_detail = client.get(f"/api/v1/projects/{project_id}/papers/{paper_id}")
        assert paper_detail.status_code == 200
        detail_payload = paper_detail.json()
        assert detail_payload["title"] == "Queued Paper"
        assert detail_payload["authors"] == ["Alice", "Bob"]
        assert detail_payload["year"] == 2024
        assert detail_payload["venue"] == "ICML"
        assert detail_payload["extraction_status"] == "PENDING"
        assert detail_payload["raw_pdf_path"] == str(saved_paths[0])

        paper_row = db.fetchone(
            "SELECT paper_id, raw_pdf_sha256 FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        assert paper_row is not None
        assert paper_row["raw_pdf_sha256"] is not None

    def test_start_data_process_project_not_found(self, client: TestClient) -> None:
        """测试项目不存在时返回 404。"""
        response = client.post(
            "/api/v1/projects/non-existent/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert response.status_code == 404

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
        project_id = create_project_resp.json()["project_id"]

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
            f"/api/v1/projects/{project_id}/data-process",
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
        db.insert(
            "papers",
            {
                "paper_id": "paper-retry-1",
                "project_id": project_id,
                "title": "Old Title",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2023,
                "venue": "Old Venue",
                "doi": "old-doi",
                "md_content": "old markdown",
                "images_paths": json.dumps(["old.png"], ensure_ascii=False),
                "extraction_status": "FAILED",
                "quick_scan": json.dumps({"old": True}, ensure_ascii=False),
                "synthesis_data": json.dumps({"old": True}, ensure_ascii=False),
                "fact_check_status": "FAILED",
                "fact_check_result": json.dumps({"error": "old"}, ensure_ascii=False),
                "extraction_retry_count": 2,
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
            f"/api/v1/projects/{project_id}/data-process/paper-retry-1/retry",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["resource_id"] == "paper-retry-1"
        assert payload["status"] == "QUEUED"
        assert payload["task_id"]

        assert len(saved_paths) == 1
        assert len(queued_tasks) == 1
        assert queued_tasks[0].payload["paper_id"] == "paper-retry-1"
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
        assert row["fact_check_result"] is None
        assert row["extraction_status"] == "PENDING"
        assert row["fact_check_status"] == "PENDING"
        assert row["raw_pdf_path"] == str(saved_paths[0])
        assert row["raw_pdf_sha256"] is not None

    def test_retry_data_process_paper_not_found(self, client: TestClient) -> None:
        """测试重试不存在的 paper 返回 404。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Retry 404 Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        response = client.post(
            f"/api/v1/projects/{project_id}/data-process/not-found/retry",
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
        db.insert(
            "papers",
            {
                "paper_id": "paper-processing",
                "project_id": project_id,
                "title": "Processing",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PROCESSING",
                "fact_check_status": "PENDING",
                "extraction_retry_count": 0,
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.post(
            f"/api/v1/projects/{project_id}/data-process/paper-processing/retry",
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
        db.insert(
            "papers",
            {
                "paper_id": "paper-manual-1",
                "project_id": project_id,
                "title": "Before",
                "authors": json.dumps(["Alice"], ensure_ascii=False),
                "year": 2022,
                "venue": "Old Venue",
                "doi": "old-doi",
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            f"/api/v1/projects/{project_id}/data-process/paper-manual-1/manual-update",
            json={
                "title": "After",
                "authors": ["Tom", "Jerry"],
                "year": 2026,
                "venue": "NeurIPS",
                "doi": "10.1/manual",
                "extraction_status": "HUMAN_COMPLETED",
                "quick_scan": {"manual": True},
                "synthesis_data": {"sections": 3},
                "fact_check_status": "HUMAN_PASSED",
                "fact_check_result": {"reviewer": "human"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["paper_id"] == "paper-manual-1"
        assert payload["title"] == "After"
        assert payload["authors"] == ["Tom", "Jerry"]
        assert payload["year"] == 2026
        assert payload["extraction_status"] == "HUMAN_COMPLETED"
        assert payload["fact_check_status"] == "HUMAN_PASSED"
        assert payload["quick_scan"] == {"manual": True}
        assert payload["synthesis_data"] == {"sections": 3}
        assert payload["fact_check_result"] == {"reviewer": "human"}

        row = db.fetchone(
            "SELECT * FROM papers WHERE paper_id = ?",
            ("paper-manual-1",),
        )
        assert row is not None
        assert row["title"] == "After"
        assert json.loads(row["authors"]) == ["Tom", "Jerry"]
        assert row["extraction_status"] == "HUMAN_COMPLETED"
        assert row["fact_check_status"] == "HUMAN_PASSED"

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
        db.insert(
            "papers",
            {
                "paper_id": "paper-manual-failed",
                "project_id": project_id,
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "PENDING",
                "fact_check_status": "PENDING",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            f"/api/v1/projects/{project_id}/data-process/paper-manual-failed/manual-update",
            json={
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "fact_check_result": {"error": "manual fail"},
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["extraction_status"] == "FAILED"
        assert payload["fact_check_status"] == "FAILED"
        assert payload["fact_check_result"] == {"error": "manual fail"}

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
        db.insert(
            "papers",
            {
                "paper_id": "paper-manual-2",
                "project_id": project_id,
                "title": "Before",
                "authors": json.dumps([], ensure_ascii=False),
                "md_content": "md",
                "images_paths": json.dumps([], ensure_ascii=False),
                "extraction_status": "FAILED",
                "fact_check_status": "FAILED",
                "created_at": now,
                "updated_at": now,
            },
        )

        response = client.patch(
            f"/api/v1/projects/{project_id}/data-process/paper-manual-2/manual-update",
            json={
                "extraction_status": "COMPLETED",
                "fact_check_status": "PASSED",
            },
        )
        assert response.status_code == 422

    def test_list_data_process_tasks(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试任务列表接口返回队列统计与任务详情。"""
        create_project_resp = client.post(
            "/api/v1/projects",
            json={"name": "Task List Project"},
        )
        assert create_project_resp.status_code == 201
        project_id = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        create_task_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert create_task_resp.status_code == 202

        list_resp = client.get(f"/api/v1/projects/{project_id}/data-process/tasks")
        assert list_resp.status_code == 200
        payload = list_resp.json()
        assert payload["project_id"] == project_id
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
        project_id = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        create_task_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert create_task_resp.status_code == 202
        task_id = create_task_resp.json()["task_id"]

        cancel_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process/tasks/{task_id}/cancel"
        )
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
        project_id = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        paper_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert paper_resp.status_code == 202
        original_task_id = paper_resp.json()["task_id"]
        paper_id = paper_resp.json()["resource_id"]

        # 手工模拟任务失败状态
        task_state = data_process_router._task_manager.task_states[original_task_id]
        task_state.status = DataProcessTaskStatus.FAILED
        task_state.error = "mock failed"
        task_state.finished_at = datetime.now()
        data_process_router._task_manager.task_states[original_task_id] = task_state

        raw_pdf_path_row = db.fetchone(
            "SELECT raw_pdf_path FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        assert raw_pdf_path_row is not None
        assert raw_pdf_path_row["raw_pdf_path"]

        retry_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process/tasks/{original_task_id}/retry"
        )
        assert retry_resp.status_code == 202
        retry_payload = retry_resp.json()
        assert retry_payload["resource_id"] == paper_id
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
        project_id = create_project_resp.json()["project_id"]

        async def fake_submit_task(
            self, task: DataProcessQueueTask
        ) -> DataProcessTaskState:
            return _stub_enqueue_state(task)

        monkeypatch.setattr(DataProcessOrchestrator, "_submit_task", fake_submit_task)

        task_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert task_resp.status_code == 202
        task_id = task_resp.json()["task_id"]

        retry_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process/tasks/{task_id}/retry"
        )
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
        project_id = create_project_resp.json()["project_id"]

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
            f"/api/v1/projects/{project_id}/data-process",
            files={"pdf_file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")},
        )
        assert start_resp.status_code == 202
        original_task_id = start_resp.json()["task_id"]
        paper_id = start_resp.json()["resource_id"]

        cancel_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process/tasks/{original_task_id}/cancel"
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELED"

        retry_resp = client.post(
            f"/api/v1/projects/{project_id}/data-process/tasks/{original_task_id}/retry"
        )
        assert retry_resp.status_code == 202
        payload = retry_resp.json()
        assert payload["resource_id"] == paper_id
        assert payload["task_id"] != original_task_id
