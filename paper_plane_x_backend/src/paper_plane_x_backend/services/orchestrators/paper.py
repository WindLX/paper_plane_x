"""Paper 编排服务（实体语义）。"""

from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from fastapi import UploadFile, status

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import Paper
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.orchestrators.data_process import (
    DataProcessDomainError,
    DataProcessOrchestrator,
)
from paper_plane_x_backend.services.paper.repository import (
    PaperRepository,
    PaperRepositoryError,
)

logger = logging.getLogger(__name__)


class PaperDomainError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class PaperOrchestrator:
    def __init__(
        self,
        db: Database,
        task_manager: DataProcessTaskManager,
    ) -> None:
        self.db = db
        self.repo = PaperRepository(db)
        self.data_process_orchestrator = DataProcessOrchestrator(
            db=db,
            task_manager=task_manager,
        )

    def list_papers(self, *, offset: int, limit: int) -> tuple[list[Paper], int]:
        count_result = self.db.fetchone("SELECT COUNT(*) AS count FROM papers")
        total = int(count_result["count"]) if count_result else 0
        papers = self.repo.list_all(offset=offset, limit=limit)
        return papers, total

    def get_paper(self, *, paper_id: str) -> Paper:
        paper = self.repo.get(paper_id)
        if paper is None:
            raise PaperDomainError(
                status.HTTP_404_NOT_FOUND, f"Paper {paper_id} not found"
            )
        return paper

    def list_paper_project_ids(self, paper_id: str) -> list[str]:
        return self.repo.list_project_ids(paper_id)

    async def create_paper_and_start_processing(
        self,
        *,
        upload_file: UploadFile,
        title: str | None,
        authors: str | None,
        year: int | None,
        publication: str | None,
        doi: str | None,
        custom_meta: str | None,
    ) -> tuple[str, str]:
        try:
            metadata = self.data_process_orchestrator.build_metadata(
                title=title,
                authors=authors,
                year=year,
                publication=publication,
                doi=doi,
                custom_meta=custom_meta,
            )
            task_state, paper_id = await self.data_process_orchestrator.start(
                upload_file=upload_file,
                metadata=metadata,
            )
            return task_state.task_id, paper_id
        except DataProcessDomainError as exc:
            raise PaperDomainError(exc.status_code, exc.detail) from exc

    async def reprocess_paper(
        self,
        *,
        paper_id: str,
        upload_file: UploadFile,
    ) -> str:
        paper = self.repo.get(paper_id)
        if paper is None:
            raise PaperDomainError(
                status.HTTP_404_NOT_FOUND, f"Paper {paper_id} not found"
            )

        try:
            task_state = await self.data_process_orchestrator.retry_upload(
                paper_id=paper_id,
                upload_file=upload_file,
            )
            return task_state.task_id
        except DataProcessDomainError as exc:
            raise PaperDomainError(exc.status_code, exc.detail) from exc

    def update_paper(
        self,
        *,
        paper_id: str,
        title: str | None,
        authors: list[str] | None,
        year: int | None,
        publication: str | None,
        doi: str | None,
        custom_meta: str | None,
        extraction_status: Any,
        quick_scan: dict[str, Any] | None,
        synthesis_data: dict[str, Any] | None,
        analysis_report: dict[str, Any] | None,
        extraction_fact_check_status: Any,
        extraction_fact_check_result: dict[str, Any] | None,
        analysis_fact_check_status: Any,
        analysis_fact_check_result: dict[str, Any] | None,
    ) -> Paper:
        if custom_meta is not None:
            self._validate_custom_meta_json(custom_meta)

        try:
            updated = self.repo.manual_update(
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
            if "not found" in exc.message.lower():
                raise PaperDomainError(status.HTTP_404_NOT_FOUND, exc.message) from exc
            raise PaperDomainError(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                f"Failed to update paper: {exc.message}",
            ) from exc

        return updated

    @staticmethod
    def _validate_custom_meta_json(custom_meta: str) -> None:
        try:
            parsed = json.loads(custom_meta)
        except json.JSONDecodeError as exc:
            raise PaperDomainError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"custom_meta must be valid JSON: {exc.msg}",
            ) from exc

        if not isinstance(parsed, dict):
            raise PaperDomainError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "custom_meta must be a JSON object",
            )

    def delete_paper(self, *, paper_id: str) -> None:
        paper = self.repo.get(paper_id)
        if paper is None:
            raise PaperDomainError(
                status.HTTP_404_NOT_FOUND, f"Paper {paper_id} not found"
            )
        if paper.extraction_status.value in {"PENDING", "PROCESSING"}:
            raise PaperDomainError(
                status.HTTP_409_CONFLICT,
                f"Paper {paper_id} is being processed and cannot be deleted",
            )

        for project_id in self.repo.list_project_ids(paper_id):
            self.repo.unlink_from_project(paper_id=paper_id, project_id=project_id)

        self.db.delete("papers", "paper_id = ?", (paper_id,))

        paper_dir = settings.mineru_output_dir / paper_id
        if paper_dir.exists():
            try:
                shutil.rmtree(paper_dir)
            except Exception:
                logger.exception(
                    "event=paper.artifacts_delete_failed paper_id=%s path=%s",
                    paper_id,
                    paper_dir,
                )
