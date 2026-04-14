"""Data-process 编排服务。

统一承接 Router 的业务编排逻辑，Router 仅保留参数解析和响应映射。
"""

import logging
from hashlib import sha256
from pathlib import Path
from typing import TypeAlias
from uuid import uuid4

from fastapi import UploadFile, status

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    ExtractionStatus,
    FactCheckStatus,
    Paper,
)
from paper_plane_x_backend.services.data_process_task_manager import (
    DataProcessQueueTask,
    DataProcessTaskManager,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper_service import PaperService, PaperServiceError

logger = logging.getLogger(__name__)

MetadataPayload: TypeAlias = dict[str, object]


class DataProcessDomainError(Exception):
    """Data-process 业务异常（由 Router 映射为 HTTP 错误）。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DataProcessOrchestrator:
    """Data-process 业务编排入口。"""

    def __init__(self, db: Database, task_manager: DataProcessTaskManager) -> None:
        self.db = db
        self.task_manager = task_manager
        self.paper_service = PaperService(db)

    def build_metadata(
        self,
        *,
        title: str | None,
        authors: str | None,
        year: int | None,
        venue: str | None,
        doi: str | None,
    ) -> MetadataPayload:
        metadata: MetadataPayload = {}

        if authors:
            metadata["authors"] = [a.strip() for a in authors.split(",") if a.strip()]

        if title is not None:
            metadata["title"] = title
        if year is not None:
            metadata["year"] = year
        if venue is not None:
            metadata["venue"] = venue
        if doi is not None:
            metadata["doi"] = doi

        return metadata

    def _ensure_project_exists(self, project_id: str) -> None:
        row = self.db.fetchone(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        )
        if not row:
            logger.warning(
                "event=data_process.project_not_found project_id=%s", project_id
            )
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Project {project_id} not found",
            )

    def _ensure_retryable_paper(self, project_id: str, paper_id: str) -> None:
        existing_paper = self.db.fetchone(
            "SELECT extraction_status FROM papers WHERE project_id = ? AND paper_id = ?",
            (project_id, paper_id),
        )
        if not existing_paper:
            logger.warning(
                "event=data_process.retry_paper_not_found project_id=%s paper_id=%s",
                project_id,
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found in project {project_id}",
            )

        if existing_paper["extraction_status"] in {
            ExtractionStatus.PENDING,
            ExtractionStatus.PROCESSING,
        }:
            logger.info(
                "event=data_process.retry_blocked project_id=%s paper_id=%s status=%s",
                project_id,
                paper_id,
                existing_paper["extraction_status"],
            )
            raise DataProcessDomainError(
                status.HTTP_409_CONFLICT,
                f"Paper {paper_id} is already in processing queue",
            )

    async def _save_upload_file(self, upload_file: UploadFile, paper_id: str) -> Path:
        upload_dir = settings.MINERU_OUTPUT_DIR / paper_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        suffix = Path(upload_file.filename or "original.pdf").suffix or ".pdf"
        pdf_path = upload_dir / f"original{suffix}"
        content = await upload_file.read()
        pdf_path.write_bytes(content)
        return pdf_path

    def _compute_pdf_sha256(self, pdf_path: Path) -> str:
        digest = sha256()
        with pdf_path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def _submit_task(self, task: DataProcessQueueTask) -> DataProcessTaskState:
        return await self.task_manager.submit_task(task)

    async def start(
        self,
        *,
        project_id: str,
        upload_file: UploadFile,
        metadata: MetadataPayload,
    ) -> tuple[DataProcessTaskState, str]:
        self._ensure_project_exists(project_id)
        logger.info("event=data_process.start_requested project_id=%s", project_id)

        try:
            paper = self.paper_service.create_pending_paper_record(
                project_id=project_id,
                metadata=metadata,
            )
            pdf_path = await self._save_upload_file(upload_file, paper.paper_id)
            raw_pdf_sha256 = self._compute_pdf_sha256(pdf_path)
            self.paper_service.set_raw_pdf_source(
                paper_id=paper.paper_id,
                raw_pdf_path=str(pdf_path),
                raw_pdf_sha256=raw_pdf_sha256,
            )

            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                project_id=project_id,
                payload={"paper_id": paper.paper_id, "pdf_path": str(pdf_path)},
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.task_queued project_id=%s paper_id=%s task_id=%s",
                project_id,
                paper.paper_id,
                task_state.task_id,
            )
            return task_state, paper.paper_id
        except PaperServiceError as exc:
            logger.exception(
                "event=data_process.start_paper_service_failed project_id=%s",
                project_id,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to start processing: {exc.message}",
            )
        except DataProcessDomainError:
            raise
        except Exception as exc:
            logger.exception("event=data_process.start_unexpected_error")
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Internal error: {exc}",
            )

    async def retry_upload(
        self,
        *,
        project_id: str,
        paper_id: str,
        upload_file: UploadFile,
    ) -> DataProcessTaskState:
        self._ensure_project_exists(project_id)
        self._ensure_retryable_paper(project_id, paper_id)
        logger.info(
            "event=data_process.retry_upload_requested project_id=%s paper_id=%s",
            project_id,
            paper_id,
        )

        try:
            pdf_path = await self._save_upload_file(upload_file, paper_id)
            raw_pdf_sha256 = self._compute_pdf_sha256(pdf_path)
            existing_paper = self.paper_service.get_paper(paper_id)
            preserve_parse_result = (
                existing_paper is not None
                and bool(existing_paper.md_content)
                and existing_paper.raw_pdf_sha256 == raw_pdf_sha256
            )
            if preserve_parse_result:
                logger.info(
                    "event=data_process.retry_upload_parse_skipped project_id=%s paper_id=%s reason=same_pdf_hash",
                    project_id,
                    paper_id,
                )

            self.paper_service.reset_paper_for_retry(
                paper_id=paper_id,
                raw_pdf_path=str(pdf_path),
                raw_pdf_sha256=raw_pdf_sha256,
                preserve_parse_result=preserve_parse_result,
            )

            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                project_id=project_id,
                payload={"paper_id": paper_id, "pdf_path": str(pdf_path)},
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.retry_upload_queued project_id=%s paper_id=%s task_id=%s",
                project_id,
                paper_id,
                task_state.task_id,
            )
            return task_state
        except PaperServiceError as exc:
            logger.exception(
                "event=data_process.retry_upload_paper_service_failed project_id=%s paper_id=%s",
                project_id,
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to retry processing: {exc.message}",
            )
        except DataProcessDomainError:
            raise
        except Exception as exc:
            logger.exception("event=data_process.retry_upload_unexpected_error")
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Internal error: {exc}",
            )

    def manual_update_paper(
        self,
        *,
        project_id: str,
        paper_id: str,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str | None = None,
        doi: str | None = None,
        extraction_status: ExtractionStatus | None = None,
        quick_scan: dict[str, object] | None = None,
        synthesis_data: dict[str, object] | None = None,
        fact_check_status: FactCheckStatus | None = None,
        fact_check_result: dict[str, object] | None = None,
    ) -> Paper:
        self._ensure_project_exists(project_id)
        paper_row = self.db.fetchone(
            "SELECT 1 FROM papers WHERE project_id = ? AND paper_id = ?",
            (project_id, paper_id),
        )
        if not paper_row:
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found in project {project_id}",
            )

        try:
            return self.paper_service.manually_update_paper(
                paper_id=paper_id,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                extraction_status=extraction_status,
                quick_scan=quick_scan,
                synthesis_data=synthesis_data,
                fact_check_status=fact_check_status,
                fact_check_result=fact_check_result,
            )
        except PaperServiceError as exc:
            logger.exception(
                "event=data_process.manual_update_failed project_id=%s paper_id=%s",
                project_id,
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to manually update paper: {exc.message}",
            )

    def list_tasks(
        self, project_id: str
    ) -> tuple[list[DataProcessTaskState], dict[str, int]]:
        self._ensure_project_exists(project_id)
        logger.debug(
            "event=data_process.tasks_list_requested project_id=%s", project_id
        )

        states = self.task_manager.list_tasks(project_id=project_id)
        counts = {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "canceled": 0,
        }
        for state in states:
            if state.status == DataProcessTaskStatus.QUEUED:
                counts["queued"] += 1
            elif state.status in {
                DataProcessTaskStatus.RUNNING,
                DataProcessTaskStatus.CANCELING,
            }:
                counts["running"] += 1
            elif state.status == DataProcessTaskStatus.COMPLETED:
                counts["completed"] += 1
            elif state.status == DataProcessTaskStatus.FAILED:
                counts["failed"] += 1
            elif state.status == DataProcessTaskStatus.CANCELED:
                counts["canceled"] += 1

        return states, counts

    def cancel(self, project_id: str, task_id: str) -> DataProcessTaskState:
        self._ensure_project_exists(project_id)
        logger.info(
            "event=data_process.cancel_requested project_id=%s task_id=%s",
            project_id,
            task_id,
        )

        state = self.task_manager.get_task(task_id)
        if state is None or state.project_id != project_id:
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Task {task_id} not found in project {project_id}",
            )

        try:
            state = self.task_manager.cancel_task(task_id)
            logger.info(
                "event=data_process.cancel_accepted project_id=%s task_id=%s status=%s",
                project_id,
                task_id,
                state.status,
            )
            return state
        except ValueError as exc:
            raise DataProcessDomainError(status.HTTP_409_CONFLICT, str(exc))

    async def retry_failed_task(
        self,
        *,
        project_id: str,
        task_id: str,
    ) -> tuple[DataProcessTaskState, str]:
        self._ensure_project_exists(project_id)
        logger.info(
            "event=data_process.retry_task_requested project_id=%s task_id=%s",
            project_id,
            task_id,
        )

        state = self.task_manager.get_task(task_id)
        if state is None or state.project_id != project_id:
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Task {task_id} not found in project {project_id}",
            )

        if state.status not in {
            DataProcessTaskStatus.FAILED,
            DataProcessTaskStatus.CANCELED,
        }:
            raise DataProcessDomainError(
                status.HTTP_409_CONFLICT,
                f"Task {task_id} status {state.status} is not retryable",
            )

        paper_id = state.payload.get("paper_id")
        if not isinstance(paper_id, str):
            raise DataProcessDomainError(
                status.HTTP_400_BAD_REQUEST,
                "Task payload missing paper_id",
            )

        paper = self.db.fetchone(
            "SELECT paper_id, raw_pdf_path FROM papers WHERE paper_id = ? AND project_id = ?",
            (paper_id, project_id),
        )
        if paper is None:
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found in project {project_id}",
            )

        raw_pdf_path = paper.get("raw_pdf_path")
        if not raw_pdf_path:
            raise DataProcessDomainError(
                status.HTTP_400_BAD_REQUEST,
                "Paper has no raw_pdf_path, please re-upload file first",
            )

        pdf_path = Path(raw_pdf_path)
        if not pdf_path.exists():
            raise DataProcessDomainError(
                status.HTTP_400_BAD_REQUEST,
                f"Raw PDF file not found: {raw_pdf_path}",
            )

        try:
            self.paper_service.reset_paper_for_retry(
                paper_id=paper_id,
                raw_pdf_path=raw_pdf_path,
            )
            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                project_id=project_id,
                payload={"paper_id": paper_id, "pdf_path": str(pdf_path)},
                retry_of_task_id=task_id,
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.retry_task_queued project_id=%s paper_id=%s old_task_id=%s new_task_id=%s",
                project_id,
                paper_id,
                task_id,
                task_state.task_id,
            )
            return task_state, paper_id
        except PaperServiceError as exc:
            logger.exception(
                "event=data_process.retry_task_paper_service_failed project_id=%s task_id=%s",
                project_id,
                task_id,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to retry task: {exc.message}",
            )
