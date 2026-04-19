"""Paper AI 处理服务.

负责论文的提取-核查闭环流水线编排，包括：
- 调用 DataProcessorAgentGroup 执行 AI 提取与事实核查
- 结果持久化到数据库
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from paper_plane_x_backend.agents import DataProcessorAgentGroup
from paper_plane_x_backend.models import ExtractionStatus, FactCheckStatus, Paper
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    AnalysisAgentOutput,
    ExtractionAgentOutput,
    FactCheckAgentOutput,
)
from paper_plane_x_backend.services.paper.parser import PaperParser
from paper_plane_x_backend.services.paper.repository import PaperRepository

logger = logging.getLogger(__name__)


class PaperProcessorError(Exception):
    """PaperProcessor 异常."""

    def __init__(self, message: str, paper_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.paper_id = paper_id


class PaperProcessor:
    """论文 AI 处理编排器."""

    def __init__(
        self,
        repo: PaperRepository,
        parser: PaperParser | None = None,
        agent_group: DataProcessorAgentGroup | None = None,
    ) -> None:
        self.repo = repo
        self.parser = parser or PaperParser()
        self.agent_group = agent_group or DataProcessorAgentGroup()

    def _log_stage(self, paper_id: str, stage: str, detail: str) -> None:
        logger.info(
            "event=paper.processing_stage paper_id=%s stage=%s detail=%s",
            paper_id,
            stage,
            detail,
        )

    async def process(
        self,
        paper_id: str,
        pdf_path: Path | None = None,
        max_retries: int = 3,
    ) -> Paper:
        """处理已存在的 Paper 记录（执行 Agent 提取）.

        Args:
            paper_id: Paper ID
            pdf_path: 可选的 PDF 路径（用于重新解析）
            max_retries: 最大重试次数

        Returns:
            Paper: 处理完成的 Paper 对象

        Raises:
            PaperProcessorError: 处理失败时抛出
        """
        paper = self.repo.get(paper_id)
        if not paper:
            raise PaperProcessorError(f"Paper {paper_id} not found")

        if paper.extraction_status == ExtractionStatus.COMPLETED:
            logger.info(
                "event=paper.processing_skipped paper_id=%s reason=already_completed",
                paper_id,
            )
            return paper

        try:
            self.repo.update_status(
                paper_id=paper_id,
                status=ExtractionStatus.PROCESSING,
            )
            logger.info("event=paper.processing_started paper_id=%s", paper_id)

            md_content, image_paths = await self.parser.prepare_inputs(
                paper_id=paper_id,
                paper=paper,
                pdf_path=pdf_path,
                update_parse_result_callback=self.repo.update_parse_result,
            )

            return await self._run_pipeline(
                paper_id=paper_id,
                md_content=md_content,
                image_paths=image_paths,
                max_retries=max_retries,
            )

        except asyncio.CancelledError:
            logger.info("event=paper.processing_canceled paper_id=%s", paper_id)
            raise
        except Exception as e:
            self._raise_error(
                paper_id=paper_id,
                stage="Failed to process paper",
                error=e,
                extraction_final_fact_check_trace_id=(
                    self.agent_group.extraction_last_fact_check_trace_id
                ),
                analysis_final_fact_check_trace_id=(
                    self.agent_group.analysis_last_fact_check_trace_id
                ),
            )

    async def _run_pipeline(
        self,
        paper_id: str,
        md_content: str,
        image_paths: list[Path],
        max_retries: int,
    ) -> Paper:
        """执行提取-核查-持久化公共流水线。"""
        self._log_stage(
            paper_id,
            "Stage 2-3",
            "Parallel extraction/analysis with feedback loops",
        )

        images_base64 = self.parser.load_images_base64(image_paths)
        try:
            (
                extraction_result,
                extraction_fact_check_result,
                extraction_retry_count,
                analysis_result,
                analysis_fact_check_result,
                analysis_retry_count,
            ) = await self.agent_group.run_parallel_loops(
                md_content=md_content,
                images=images_base64,
                max_retries=max_retries,
            )
        except RuntimeError as e:
            raise PaperProcessorError(str(e), paper_id=paper_id) from e

        extraction_final_fact_check_trace_id = (
            self.agent_group.extraction_last_fact_check_trace_id
        )
        analysis_final_fact_check_trace_id = (
            self.agent_group.analysis_last_fact_check_trace_id
        )

        self._log_stage(paper_id, "Stage 4", "Saving results to database")
        paper = self._save_pipeline_result(
            paper_id=paper_id,
            extraction_result=extraction_result,
            analysis_result=analysis_result,
            extraction_fact_check_result=extraction_fact_check_result,
            analysis_fact_check_result=analysis_fact_check_result,
            extraction_retry_count=extraction_retry_count,
            analysis_retry_count=analysis_retry_count,
            extraction_final_fact_check_trace_id=extraction_final_fact_check_trace_id,
            analysis_final_fact_check_trace_id=analysis_final_fact_check_trace_id,
        )

        logger.info("event=paper.processing_completed paper_id=%s", paper_id)
        return paper

    def _raise_error(
        self,
        paper_id: str,
        stage: str,
        error: Exception,
        extraction_final_fact_check_trace_id: str | None = None,
        analysis_final_fact_check_trace_id: str | None = None,
    ) -> NoReturn:
        """统一处理失败状态更新与异常抛出。"""
        logger.exception(
            "event=paper.processing_failed paper_id=%s error=%s", paper_id, error
        )
        try:
            self.repo.update_status(
                paper_id=paper_id,
                status=ExtractionStatus.FAILED,
                error_message=str(error),
                extraction_final_fact_check_trace_id=extraction_final_fact_check_trace_id,
                analysis_final_fact_check_trace_id=analysis_final_fact_check_trace_id,
            )
        except Exception as update_error:
            logger.error(
                "event=paper.error_status_update_failed paper_id=%s error=%s",
                paper_id,
                update_error,
            )

        raise PaperProcessorError(
            message=f"{stage}: {error}",
            paper_id=paper_id,
        ) from error

    def _save_pipeline_result(
        self,
        paper_id: str,
        extraction_result: ExtractionAgentOutput,
        analysis_result: AnalysisAgentOutput,
        extraction_fact_check_result: FactCheckAgentOutput,
        analysis_fact_check_result: FactCheckAgentOutput,
        extraction_retry_count: int,
        analysis_retry_count: int,
        extraction_final_fact_check_trace_id: str | None,
        analysis_final_fact_check_trace_id: str | None,
    ) -> Paper:
        """更新 Paper 记录为完成状态."""
        is_all_passed = (
            extraction_fact_check_result.is_passed
            and analysis_fact_check_result.is_passed
        )

        update_data: dict[str, object] = {
            "extraction_status": (
                ExtractionStatus.COMPLETED
                if is_all_passed
                else ExtractionStatus.HUMAN_COMPLETED
            ),
            "quick_scan": json.dumps(
                extraction_result.quick_scan.model_dump(), ensure_ascii=False
            ),
            "synthesis_data": json.dumps(
                extraction_result.synthesis_data.model_dump(), ensure_ascii=False
            ),
            "analysis_report": json.dumps(
                analysis_result.analysis_report.model_dump(), ensure_ascii=False
            ),
            "extraction_fact_check_status": (
                FactCheckStatus.PASSED
                if extraction_fact_check_result.is_passed
                else FactCheckStatus.FAILED
            ),
            "extraction_fact_check_result": json.dumps(
                extraction_fact_check_result.model_dump(), ensure_ascii=False
            ),
            "extraction_final_fact_check_trace_id": extraction_final_fact_check_trace_id,
            "analysis_fact_check_status": (
                FactCheckStatus.PASSED
                if analysis_fact_check_result.is_passed
                else FactCheckStatus.FAILED
            ),
            "analysis_fact_check_result": json.dumps(
                analysis_fact_check_result.model_dump(), ensure_ascii=False
            ),
            "analysis_final_fact_check_trace_id": analysis_final_fact_check_trace_id,
            "extraction_retry_count": extraction_retry_count,
            "analysis_retry_count": analysis_retry_count,
            "updated_at": datetime.now(),
        }

        if not is_all_passed:
            logger.warning(
                "event=paper.fact_check_failed paper_id=%s extraction_retries=%s analysis_retries=%s",
                paper_id,
                extraction_retry_count,
                analysis_retry_count,
            )

        self.repo.update(paper_id, update_data)

        updated = self.repo.get(paper_id)
        if updated is None:
            raise PaperProcessorError(
                f"Paper {paper_id} not found after update",
                paper_id=paper_id,
            )
        return updated
