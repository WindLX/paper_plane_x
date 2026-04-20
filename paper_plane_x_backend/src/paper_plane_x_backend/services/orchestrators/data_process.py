"""Data-process 编排服务。

统一承接 Router 的业务编排逻辑，Router 仅保留参数解析和响应映射。
"""

import json
import logging
from datetime import datetime
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
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessQueueTask,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import (
    PaperRepository,
    PaperRepositoryError,
)

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

    def __init__(
        self,
        db: Database,
        task_manager: DataProcessTaskManager,
    ) -> None:
        self.db = db
        self.task_manager = task_manager
        self.paper_repo = PaperRepository(db)

    def build_metadata(
        self,
        *,
        title: str | None,
        authors: str | None,
        year: int | None,
        publication: str | None,
        doi: str | None,
        custom_meta: str | None,
    ) -> MetadataPayload:
        metadata: MetadataPayload = {}

        if authors:
            metadata["authors"] = [a.strip() for a in authors.split(",") if a.strip()]

        if title is not None:
            metadata["title"] = title
        if year is not None:
            metadata["year"] = year
        if publication is not None:
            metadata["publication"] = publication
        if doi is not None:
            metadata["doi"] = doi
        if custom_meta is not None:
            metadata["custom_meta"] = self._validate_custom_meta_json(custom_meta)

        return metadata

    @staticmethod
    def _validate_custom_meta_json(custom_meta: str) -> str:
        try:
            parsed = json.loads(custom_meta)
        except json.JSONDecodeError as exc:
            raise DataProcessDomainError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"custom_meta must be valid JSON: {exc.msg}",
            ) from exc

        if not isinstance(parsed, dict):
            raise DataProcessDomainError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "custom_meta must be a JSON object",
            )
        return custom_meta

    def _ensure_retryable_paper(self, paper_id: str) -> None:
        existing_paper = self.db.fetchone(
            """
            SELECT extraction_status
            FROM papers
            WHERE paper_id = ?
            """,
            (paper_id,),
        )
        if not existing_paper:
            logger.warning(
                "event=data_process.retry_paper_not_found paper_id=%s",
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found",
            )

        if existing_paper["extraction_status"] in {
            ExtractionStatus.PENDING,
            ExtractionStatus.PROCESSING,
        }:
            logger.info(
                "event=data_process.retry_blocked paper_id=%s status=%s",
                paper_id,
                existing_paper["extraction_status"],
            )
            raise DataProcessDomainError(
                status.HTTP_409_CONFLICT,
                f"Paper {paper_id} is already in processing queue",
            )

    async def _save_upload_file(self, upload_file: UploadFile, paper_id: str) -> Path:
        upload_dir = settings.mineru.output_dir / paper_id
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

    def _reset_paper_for_retry(
        self,
        *,
        paper_id: str,
        raw_pdf_path: str | None = None,
        raw_pdf_sha256: str | None = None,
        preserve_parse_result: bool = False,
    ) -> Paper:
        paper = self.paper_repo.get(paper_id)
        if paper is None:
            raise PaperRepositoryError(f"Paper {paper_id} not found", paper_id=paper_id)

        update_data: dict[str, object] = {
            "quick_scan": None,
            "synthesis_data": None,
            "analysis_report": None,
            "extraction_fact_check_result": None,
            "extraction_final_fact_check_trace_id": None,
            "analysis_fact_check_result": None,
            "analysis_final_fact_check_trace_id": None,
            "extraction_retry_count": 0,
            "analysis_retry_count": 0,
            "extraction_status": ExtractionStatus.PENDING,
            "extraction_fact_check_status": FactCheckStatus.PENDING,
            "analysis_fact_check_status": FactCheckStatus.PENDING,
            "updated_at": datetime.now(),
        }

        if not preserve_parse_result:
            update_data["md_content"] = ""
            update_data["images_paths"] = json.dumps([], ensure_ascii=False)

        if raw_pdf_path is not None:
            update_data["raw_pdf_path"] = raw_pdf_path
        if raw_pdf_sha256 is not None:
            update_data["raw_pdf_sha256"] = raw_pdf_sha256

        self.paper_repo.update(paper_id, update_data)
        return paper

    async def _submit_task(self, task: DataProcessQueueTask) -> DataProcessTaskState:
        return await self.task_manager.submit_task(task)

    async def start(
        self,
        *,
        upload_file: UploadFile,
        metadata: MetadataPayload,
    ) -> tuple[DataProcessTaskState, str]:
        logger.info(
            "event=data_process.start_requested filename=%s metadata_keys=%s",
            upload_file.filename,
            sorted(metadata.keys()),
        )

        try:
            paper = self.paper_repo.create(
                extraction_status=ExtractionStatus.PENDING,
                metadata=metadata,
            )
            pdf_path = await self._save_upload_file(upload_file, paper.paper_id)
            raw_pdf_sha256 = self._compute_pdf_sha256(pdf_path)

            reusable_paper = self.paper_repo.find_by_pdf_hash(
                raw_pdf_sha256=raw_pdf_sha256,
            )
            if reusable_paper is not None:
                if any(metadata.get(k) is not None for k in metadata):
                    logger.warning(
                        "event=data_process.metadata_ignored_due_to_hash_reuse source_paper_id=%s",
                        reusable_paper.paper_id,
                    )
                self.db.delete("papers", "paper_id = ?", (paper.paper_id,))

                if reusable_paper.extraction_status in {
                    ExtractionStatus.COMPLETED,
                    ExtractionStatus.HUMAN_COMPLETED,
                }:
                    task_state = DataProcessTaskState(
                        task_id=str(uuid4()),
                        paper_id=reusable_paper.paper_id,
                        payload={
                            "pdf_path": reusable_paper.raw_pdf_path or str(pdf_path),
                        },
                        status=DataProcessTaskStatus.COMPLETED,
                        created_at=datetime.now(),
                        started_at=datetime.now(),
                        finished_at=datetime.now(),
                    )
                    logger.info(
                        "event=data_process.paper_reused_completed paper_id=%s",
                        reusable_paper.paper_id,
                    )
                    return task_state, reusable_paper.paper_id

                if reusable_paper.extraction_status in {
                    ExtractionStatus.PENDING,
                    ExtractionStatus.PROCESSING,
                }:
                    logger.info(
                        "event=data_process.paper_reused_conflict_processing paper_id=%s status=%s",
                        reusable_paper.paper_id,
                        reusable_paper.extraction_status,
                    )
                    raise DataProcessDomainError(
                        status.HTTP_409_CONFLICT,
                        (
                            "Paper already exists and is still processing: "
                            f"{reusable_paper.paper_id}"
                        ),
                    )

                if reusable_paper.extraction_status != ExtractionStatus.FAILED:
                    logger.warning(
                        "event=data_process.paper_reused_unexpected_status paper_id=%s status=%s",
                        reusable_paper.paper_id,
                        reusable_paper.extraction_status,
                    )
                    raise DataProcessDomainError(
                        status.HTTP_409_CONFLICT,
                        (
                            "Paper already exists but is not retryable with current status: "
                            f"{reusable_paper.extraction_status}"
                        ),
                    )

                queue_task = DataProcessQueueTask(
                    task_id=str(uuid4()),
                    paper_id=reusable_paper.paper_id,
                    payload={
                        "pdf_path": reusable_paper.raw_pdf_path or str(pdf_path),
                    },
                )
                task_state = await self._submit_task(queue_task)
                logger.info(
                    "event=data_process.paper_reused_by_hash paper_id=%s source_paper_id=%s task_id=%s",
                    reusable_paper.paper_id,
                    reusable_paper.paper_id,
                    task_state.task_id,
                )
                return task_state, reusable_paper.paper_id

            self.paper_repo.set_raw_pdf_source(
                paper_id=paper.paper_id,
                raw_pdf_path=str(pdf_path),
                raw_pdf_sha256=raw_pdf_sha256,
            )
            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                paper_id=paper.paper_id,
                payload={"pdf_path": str(pdf_path)},
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.task_queued paper_id=%s task_id=%s",
                paper.paper_id,
                task_state.task_id,
            )
            return task_state, paper.paper_id
        except PaperRepositoryError as exc:
            logger.exception(
                "event=data_process.start_paper_repo_failed filename=%s error=%s",
                upload_file.filename,
                exc.message,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to start processing: {exc.message}",
            )
        except DataProcessDomainError:
            raise
        except Exception as exc:
            logger.exception(
                "event=data_process.start_unexpected_error filename=%s",
                upload_file.filename,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Internal error: {exc}",
            )

    async def retry_upload(
        self,
        *,
        paper_id: str,
        upload_file: UploadFile,
    ) -> DataProcessTaskState:
        self._ensure_retryable_paper(paper_id)
        logger.info(
            "event=data_process.retry_upload_requested paper_id=%s filename=%s",
            paper_id,
            upload_file.filename,
        )

        try:
            pdf_path = await self._save_upload_file(upload_file, paper_id)
            raw_pdf_sha256 = self._compute_pdf_sha256(pdf_path)
            existing_paper = self.paper_repo.get(paper_id)
            preserve_parse_result = (
                existing_paper is not None
                and bool(existing_paper.md_content)
                and existing_paper.raw_pdf_sha256 == raw_pdf_sha256
            )
            if preserve_parse_result:
                logger.info(
                    "event=data_process.retry_upload_parse_skipped paper_id=%s reason=same_pdf_hash",
                    paper_id,
                )

            old_paper = self._reset_paper_for_retry(
                paper_id=paper_id,
                raw_pdf_path=str(pdf_path),
                raw_pdf_sha256=raw_pdf_sha256,
                preserve_parse_result=preserve_parse_result,
            )
            _ = old_paper

            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                paper_id=paper_id,
                payload={"pdf_path": str(pdf_path)},
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.retry_upload_queued paper_id=%s task_id=%s",
                paper_id,
                task_state.task_id,
            )
            return task_state
        except PaperRepositoryError as exc:
            logger.exception(
                "event=data_process.retry_upload_paper_repo_failed paper_id=%s",
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to retry processing: {exc.message}",
            )
        except DataProcessDomainError:
            raise
        except Exception as exc:
            logger.exception(
                "event=data_process.retry_upload_unexpected_error paper_id=%s filename=%s",
                paper_id,
                upload_file.filename,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Internal error: {exc}",
            )

    def update_paper(
        self,
        *,
        paper_id: str,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        publication: str | None = None,
        doi: str | None = None,
        custom_meta: str | None = None,
        extraction_status: ExtractionStatus | None = None,
        quick_scan: dict[str, object] | None = None,
        synthesis_data: dict[str, object] | None = None,
        analysis_report: dict[str, object] | None = None,
        extraction_fact_check_status: FactCheckStatus | None = None,
        extraction_fact_check_result: dict[str, object] | None = None,
        analysis_fact_check_status: FactCheckStatus | None = None,
        analysis_fact_check_result: dict[str, object] | None = None,
    ) -> Paper:
        paper_row = self.db.fetchone(
            "SELECT 1 FROM papers WHERE paper_id = ?", (paper_id,)
        )
        if not paper_row:
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found",
            )

        try:
            updated = self.paper_repo.manual_update(
                paper_id=paper_id,
                title=title,
                authors=authors,
                year=year,
                publication=publication,
                doi=doi,
                custom_meta=custom_meta,
                extraction_status=extraction_status,
                quick_scan=quick_scan,
                synthesis_data=synthesis_data,
                analysis_report=analysis_report,
                extraction_fact_check_status=extraction_fact_check_status,
                extraction_fact_check_result=extraction_fact_check_result,
                analysis_fact_check_status=analysis_fact_check_status,
                analysis_fact_check_result=analysis_fact_check_result,
            )
        except PaperRepositoryError as exc:
            logger.exception(
                "event=data_process.update_failed paper_id=%s error=%s",
                paper_id,
                exc.message,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to update paper: {exc.message}",
            )

        return updated

    def list_tasks(self) -> tuple[list[DataProcessTaskState], dict[str, int]]:
        logger.debug("event=data_process.tasks_list_requested")

        states = self.task_manager.list_tasks()
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

    def cancel(
        self,
        task_id: str,
    ) -> DataProcessTaskState:
        logger.info("event=data_process.cancel_requested task_id=%s", task_id)

        state = self.task_manager.get_task(task_id)
        if state is None:
            logger.warning("event=data_process.cancel_not_found task_id=%s", task_id)
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Task {task_id} not found",
            )

        try:
            state = self.task_manager.cancel_task(task_id)
            logger.info(
                "event=data_process.cancel_accepted task_id=%s status=%s",
                task_id,
                state.status,
            )
            return state
        except ValueError as exc:
            raise DataProcessDomainError(status.HTTP_409_CONFLICT, str(exc))

    async def retry_failed_task(
        self,
        *,
        task_id: str,
    ) -> tuple[DataProcessTaskState, str]:
        logger.info("event=data_process.retry_task_requested task_id=%s", task_id)

        state = self.task_manager.get_task(task_id)
        if state is None:
            logger.warning(
                "event=data_process.retry_task_not_found task_id=%s", task_id
            )
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Task {task_id} not found",
            )

        if state.status not in {
            DataProcessTaskStatus.FAILED,
            DataProcessTaskStatus.CANCELED,
        }:
            logger.warning(
                "event=data_process.retry_task_conflict task_id=%s status=%s",
                task_id,
                state.status,
            )
            raise DataProcessDomainError(
                status.HTTP_409_CONFLICT,
                f"Task {task_id} status {state.status} is not retryable",
            )

        paper_id = state.paper_id

        paper = self.db.fetchone(
            """
            SELECT paper_id, raw_pdf_path
            FROM papers
            WHERE paper_id = ?
            """,
            (paper_id,),
        )
        if paper is None:
            logger.warning(
                "event=data_process.retry_task_paper_not_found task_id=%s paper_id=%s",
                task_id,
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_404_NOT_FOUND,
                f"Paper {paper_id} not found",
            )

        raw_pdf_path = paper.get("raw_pdf_path")
        if not raw_pdf_path:
            logger.warning(
                "event=data_process.retry_task_missing_raw_pdf_path task_id=%s paper_id=%s",
                task_id,
                paper_id,
            )
            raise DataProcessDomainError(
                status.HTTP_400_BAD_REQUEST,
                "Paper has no raw_pdf_path, please re-upload file first",
            )

        pdf_path = Path(raw_pdf_path)
        if not pdf_path.exists():
            logger.warning(
                "event=data_process.retry_task_raw_pdf_not_found task_id=%s paper_id=%s raw_pdf_path=%s",
                task_id,
                paper_id,
                raw_pdf_path,
            )
            raise DataProcessDomainError(
                status.HTTP_400_BAD_REQUEST,
                f"Raw PDF file not found: {raw_pdf_path}",
            )

        try:
            old_paper = self._reset_paper_for_retry(
                paper_id=paper_id,
                raw_pdf_path=raw_pdf_path,
            )
            _ = old_paper

            queue_task = DataProcessQueueTask(
                task_id=str(uuid4()),
                paper_id=paper_id,
                payload={"pdf_path": str(pdf_path)},
                retry_of_task_id=task_id,
            )
            task_state = await self._submit_task(queue_task)
            logger.info(
                "event=data_process.retry_task_queued paper_id=%s old_task_id=%s new_task_id=%s",
                paper_id,
                task_id,
                task_state.task_id,
            )
            return task_state, paper_id
        except PaperRepositoryError as exc:
            logger.exception(
                "event=data_process.retry_task_paper_repo_failed task_id=%s paper_id=%s error=%s",
                task_id,
                paper_id,
                exc.message,
            )
            raise DataProcessDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to retry task: {exc.message}",
            )
