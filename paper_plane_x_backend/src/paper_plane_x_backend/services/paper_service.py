"""Paper 处理服务.

封装完整的 Data Process 流程：
- PDF 解析（MinerU）
- 数据提取（ExtractionAgent）
- 事实核查（FactCheckAgent）
- 反馈闭环（重试机制）
- 数据入库（SQLite）
"""

import base64
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import NoReturn, TypeAlias, cast
from uuid import uuid4

from paper_plane_x_backend.agents import (
    DataProcessorAgentGroup,
    ExtractionAgent,
    FactCheckAgent,
)
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import ExtractionStatus, FactCheckStatus, Paper
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    ExtractionAgentOutput,
    FactCheckAgentOutput,
)
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.mineru import MinerUClient, MinerUOutput

logger = logging.getLogger(__name__)

MetadataPayload: TypeAlias = dict[str, object]


class PaperServiceError(Exception):
    """Paper 服务异常."""

    def __init__(self, message: str, paper_id: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.paper_id = paper_id


class PaperService:
    """论文处理服务.

    协调 MinerU、ExtractionAgent、FactCheckAgent 完成论文的完整处理流程。
    """

    def __init__(
        self,
        db: Database,
        mineru_client: MinerUClient | None = None,
        data_processor_group: DataProcessorAgentGroup | None = None,
        extraction_agent: ExtractionAgent | None = None,
        fact_check_agent: FactCheckAgent | None = None,
    ) -> None:
        """初始化 PaperService.

        Args:
            db: 数据库实例
            mineru_client: MinerU 客户端，None 创建默认实例
            data_processor_group: 数据处理 Agent 组编排器（优先）
            extraction_agent: 提取 Agent，None 创建默认实例
            fact_check_agent: 核查 Agent，None 创建默认实例
        """
        self.db = db
        self.mineru = mineru_client or MinerUClient(
            base_url=getattr(settings, "MINERU_BASE_URL", "http://localhost:7860"),
            output_dir=getattr(settings, "MINERU_OUTPUT_DIR", Path("./data/papers")),
        )
        if data_processor_group is not None:
            self.data_processor_group = data_processor_group
        else:
            self.data_processor_group = DataProcessorAgentGroup(
                extraction_agent=extraction_agent,
                fact_check_agent=fact_check_agent,
            )

    def _log_stage(self, paper_id: str, stage: str, detail: str) -> None:
        logger.info(
            "event=paper.processing_stage paper_id=%s stage=%s detail=%s",
            paper_id,
            stage,
            detail,
        )

    async def process_pdf(
        self,
        project_id: str,
        pdf_path: Path,
        metadata: MetadataPayload | None = None,
        max_retries: int = 3,
    ) -> Paper:
        """处理 PDF 论文.

        完整流程：
        1. 调用 MinerU 解析 PDF
        2. 创建 Paper 记录（状态 PROCESSING）
        3. 提取-核查闭环循环
        4. 更新 Paper 记录（状态 COMPLETED/FAILED）

        Args:
            project_id: 所属项目 ID
            pdf_path: PDF 文件路径
            metadata: 论文元数据（标题、作者等）
            max_retries: 最大重试次数

        Returns:
            Paper: 处理完成的 Paper 对象

        Raises:
            PaperServiceError: 处理失败时抛出
        """
        paper_id = str(uuid4())
        metadata = metadata or {}

        try:
            md_content, image_paths = await self._parse_to_processing_inputs(
                pdf_path=pdf_path,
                paper_id=paper_id,
            )

            # 创建 Paper 记录
            paper = self._create_paper_record(
                paper_id=paper_id,
                project_id=project_id,
                md_content=md_content,
                raw_pdf_path=str(pdf_path),
                images_paths=[str(p) for p in image_paths],
                metadata=metadata,
            )

            return await self._run_processing_pipeline(
                paper_id=paper.paper_id,
                md_content=md_content,
                image_paths=image_paths,
                max_retries=max_retries,
            )

        except Exception as e:
            self._raise_processing_error(
                paper_id=paper_id,
                stage="Failed to process PDF",
                error=e,
                final_fact_check_trace_id=self.data_processor_group.last_fact_check_trace_id,
            )

    def create_pending_paper_record(
        self,
        project_id: str,
        metadata: MetadataPayload | None = None,
    ) -> Paper:
        """创建待处理的 Paper 记录（不执行解析与提取）.

        Args:
            project_id: 项目 ID
            metadata: 论文元数据

        Returns:
            Paper: 新创建的待处理记录
        """
        paper_id = str(uuid4())
        metadata = metadata or {}
        return self._create_paper_record(
            paper_id=paper_id,
            project_id=project_id,
            md_content="",
            images_paths=[],
            metadata=metadata,
            extraction_status=ExtractionStatus.PENDING,
        )

    def set_raw_pdf_source(
        self,
        paper_id: str,
        raw_pdf_path: str,
        raw_pdf_sha256: str | None = None,
    ) -> None:
        """更新 Paper 的原始 PDF 路径与可选 hash。"""
        update_data: dict[str, object] = {
            "raw_pdf_path": raw_pdf_path,
            "updated_at": datetime.now(),
        }
        if raw_pdf_sha256 is not None:
            update_data["raw_pdf_sha256"] = raw_pdf_sha256

        self.db.update(
            table="papers",
            data=update_data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

    def manually_update_paper(
        self,
        *,
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
        """人工更新 Paper 元数据和处理结果。"""
        paper = self.get_paper(paper_id)
        if paper is None:
            raise PaperServiceError(f"Paper {paper_id} not found", paper_id=paper_id)

        update_data: dict[str, object] = {"updated_at": datetime.now()}

        if title is not None:
            update_data["title"] = title
        if authors is not None:
            update_data["authors"] = json.dumps(authors, ensure_ascii=False)
        if year is not None:
            update_data["year"] = year
        if venue is not None:
            update_data["venue"] = venue
        if doi is not None:
            update_data["doi"] = doi
        if extraction_status is not None:
            update_data["extraction_status"] = extraction_status
        if quick_scan is not None:
            update_data["quick_scan"] = json.dumps(quick_scan, ensure_ascii=False)
        if synthesis_data is not None:
            update_data["synthesis_data"] = json.dumps(
                synthesis_data, ensure_ascii=False
            )
        if fact_check_status is not None:
            update_data["fact_check_status"] = fact_check_status
        if fact_check_result is not None:
            update_data["fact_check_result"] = json.dumps(
                fact_check_result, ensure_ascii=False
            )

        self.db.update(
            table="papers",
            data=update_data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

        updated = self.get_paper(paper_id)
        if updated is None:
            raise PaperServiceError(
                f"Paper {paper_id} not found after manual update",
                paper_id=paper_id,
            )
        return updated

    def reset_paper_for_retry(
        self,
        paper_id: str,
        raw_pdf_path: str | None = None,
        raw_pdf_sha256: str | None = None,
        preserve_parse_result: bool = False,
    ) -> None:
        """重置已有 Paper，供同 ID 重新上传后重试处理。

        Args:
            paper_id: 目标 Paper ID
            raw_pdf_path: 新上传原始 PDF 路径
            raw_pdf_sha256: 新上传原始 PDF 的 SHA256 哈希
            preserve_parse_result: 是否保留已有的解析结果

        Raises:
            PaperServiceError: Paper 不存在
        """
        paper = self.get_paper(paper_id)
        if paper is None:
            raise PaperServiceError(f"Paper {paper_id} not found", paper_id=paper_id)

        update_data: dict[str, object] = {
            "quick_scan": None,
            "synthesis_data": None,
            "fact_check_result": None,
            "final_fact_check_trace_id": None,
            "extraction_retry_count": 0,
            "extraction_status": ExtractionStatus.PENDING,
            "fact_check_status": FactCheckStatus.PENDING,
            "updated_at": datetime.now(),
        }

        if not preserve_parse_result:
            update_data["md_content"] = ""
            update_data["images_paths"] = json.dumps([], ensure_ascii=False)

        if raw_pdf_path is not None:
            update_data["raw_pdf_path"] = raw_pdf_path
        if raw_pdf_sha256 is not None:
            update_data["raw_pdf_sha256"] = raw_pdf_sha256

        self.db.update(
            table="papers",
            data=update_data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

    async def _parse_pdf(
        self,
        pdf_path: Path,
        paper_id: str,
    ) -> MinerUOutput:
        """使用 MinerU 解析 PDF.

        Args:
            pdf_path: PDF 文件路径
            paper_id: Paper ID（用于目录命名）

        Returns:
            MinerUOutput: 解析结果
        """
        # 创建解析输出目录
        output_dir = settings.MINERU_OUTPUT_DIR / paper_id
        output_dir.mkdir(parents=True, exist_ok=True)

        # 调用 MinerU（异步方法）
        result = await self.mineru.parse_pdf(
            file_path=pdf_path,
            output_md_name=f"{paper_id}.md",
            save_dir=output_dir,
        )

        return result

    async def _parse_to_processing_inputs(
        self,
        pdf_path: Path,
        paper_id: str,
    ) -> tuple[str, list[Path]]:
        """统一将 PDF 解析为闭环所需输入。"""
        self._log_stage(paper_id, "Stage 1", "Parsing PDF with MinerU")
        mineru_output = await self._parse_pdf(pdf_path, paper_id)
        return mineru_output.md_content, mineru_output.image_paths

    async def _prepare_existing_processing_inputs(
        self,
        paper_id: str,
        paper: Paper,
        pdf_path: Path | None,
    ) -> tuple[str, list[Path]]:
        """为 existing paper 准备闭环输入。

        若记录已有 md_content，直接使用；否则要求提供 pdf_path 重新解析。
        """
        md_content = paper.md_content
        image_paths: list[Path] = [Path(p) for p in paper.images_paths]

        if md_content:
            return md_content, image_paths

        if pdf_path is None:
            raise PaperServiceError(
                "Paper has no markdown content and no PDF path provided"
            )

        md_content, image_paths = await self._parse_to_processing_inputs(
            pdf_path=pdf_path,
            paper_id=paper_id,
        )
        self._update_paper_with_parse_result(
            paper_id=paper_id,
            md_content=md_content,
            images_paths=[str(p) for p in image_paths],
        )
        return md_content, image_paths

    def _create_paper_record(
        self,
        paper_id: str,
        project_id: str,
        md_content: str,
        images_paths: list[str],
        metadata: MetadataPayload,
        raw_pdf_path: str | None = None,
        raw_pdf_sha256: str | None = None,
        extraction_status: ExtractionStatus = ExtractionStatus.PROCESSING,
    ) -> Paper:
        """创建 Paper 数据库记录.

        Args:
            paper_id: Paper ID
            project_id: 项目 ID
            md_content: Markdown 内容
            images_paths: 图片路径列表
            metadata: 元数据（标题、作者等）

        Returns:
            Paper: 创建的 Paper 对象
        """
        now = datetime.now()

        title = self._metadata_optional_str(metadata, "title")
        authors = self._metadata_authors(metadata) or []
        year = self._metadata_optional_int(metadata, "year")
        venue = self._metadata_optional_str(metadata, "venue")
        doi = self._metadata_optional_str(metadata, "doi")

        paper = Paper(
            paper_id=paper_id,
            project_id=project_id,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            md_content=md_content,
            raw_pdf_path=raw_pdf_path,
            raw_pdf_sha256=raw_pdf_sha256,
            images_paths=images_paths,
            extraction_status=extraction_status,
            quick_scan=None,
            synthesis_data=None,
            fact_check_status=FactCheckStatus.PENDING,
            fact_check_result=None,
            final_fact_check_trace_id=None,
            extraction_retry_count=0,
            created_at=now,
            updated_at=now,
        )

        self.db.insert("papers", paper.to_db_dict())
        logger.info("event=paper.record_created paper_id=%s", paper_id)

        return paper

    def _metadata_optional_str(self, metadata: MetadataPayload, key: str) -> str | None:
        value = metadata.get(key)
        if isinstance(value, str):
            return value
        return None

    def _metadata_optional_int(self, metadata: MetadataPayload, key: str) -> int | None:
        value = metadata.get(key)
        if isinstance(value, int):
            return value
        return None

    def _metadata_authors(self, metadata: MetadataPayload) -> list[str] | None:
        value = metadata.get("authors")
        if isinstance(value, list):
            values = cast(list[object], value)
            authors: list[str] = []
            for item in values:
                if isinstance(item, str):
                    authors.append(item)
            return authors
        if isinstance(value, str):
            return [a.strip() for a in value.split(",") if a.strip()]
        return None

    def _load_images_as_base64(self, image_paths: list[Path]) -> list[str]:
        """将图片加载为 base64 编码.

        Args:
            image_paths: 图片路径列表

        Returns:
            list[str]: base64 编码的图片列表
        """
        images_base64: list[str] = []
        for img_path in image_paths:
            try:
                with open(img_path, "rb") as f:
                    img_data = f.read()
                    # 检测图片类型
                    ext = img_path.suffix.lower()
                    mime_type = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".gif": "image/gif",
                        ".webp": "image/webp",
                    }.get(ext, "image/png")

                    b64_data = base64.b64encode(img_data).decode("utf-8")
                    images_base64.append(f"data:{mime_type};base64,{b64_data}")
            except Exception as e:
                logger.warning(
                    "event=paper.image_load_failed image_path=%s error=%s",
                    img_path,
                    e,
                )

        return images_base64

    async def _run_processing_pipeline(
        self,
        paper_id: str,
        md_content: str,
        image_paths: list[Path],
        max_retries: int,
    ) -> Paper:
        """执行提取-核查-持久化公共流水线。"""
        self._log_stage(paper_id, "Stage 2-3", "Extraction with feedback loop")

        images_base64 = self._load_images_as_base64(image_paths)
        extraction_result, fact_check_result, retry_count = (
            await self._extraction_with_feedback_loop(
                paper_id=paper_id,
                md_content=md_content,
                images=images_base64,
                max_retries=max_retries,
            )
        )
        final_fact_check_trace_id = self.data_processor_group.last_fact_check_trace_id

        self._log_stage(paper_id, "Stage 4", "Saving results to database")
        paper = self._update_paper_with_extraction_result(
            paper_id=paper_id,
            extraction_result=extraction_result,
            fact_check_result=fact_check_result,
            retry_count=retry_count,
            final_fact_check_trace_id=final_fact_check_trace_id,
        )

        logger.info("event=paper.processing_completed paper_id=%s", paper_id)
        return paper

    def _raise_processing_error(
        self,
        paper_id: str,
        stage: str,
        error: Exception,
        final_fact_check_trace_id: str | None = None,
    ) -> NoReturn:
        """统一处理失败状态更新与异常抛出。"""
        logger.exception(
            "event=paper.processing_failed paper_id=%s error=%s", paper_id, error
        )
        try:
            self._update_paper_status(
                paper_id=paper_id,
                status=ExtractionStatus.FAILED,
                error_message=str(error),
                final_fact_check_trace_id=final_fact_check_trace_id,
            )
        except Exception as update_error:
            logger.error(
                "event=paper.error_status_update_failed paper_id=%s error=%s",
                paper_id,
                update_error,
            )

        raise PaperServiceError(
            message=f"{stage}: {error}",
            paper_id=paper_id,
        ) from error

    async def _extraction_with_feedback_loop(
        self,
        paper_id: str,
        md_content: str,
        images: list[str],
        max_retries: int,
    ) -> tuple[ExtractionAgentOutput, FactCheckAgentOutput, int]:
        """提取-核查反馈闭环.

        循环执行提取和核查，直到通过或达到最大重试次数。

        Args:
            paper_id: Paper ID
            md_content: Markdown 内容
            images: base64 编码的图片列表
            max_retries: 最大重试次数

        Returns:
            tuple: (提取结果, 核查结果, 实际重试次数)

        Raises:
            PaperServiceError: 多次核查失败时抛出
        """
        try:
            return await self.data_processor_group.run_extraction_fact_check_loop(
                project_id=paper_id,
                md_content=md_content,
                images=images,
                max_retries=max_retries,
            )
        except RuntimeError as e:
            raise PaperServiceError(str(e), paper_id=paper_id) from e

    def _update_paper_with_extraction_result(
        self,
        paper_id: str,
        extraction_result: ExtractionAgentOutput,
        fact_check_result: FactCheckAgentOutput,
        retry_count: int,
        final_fact_check_trace_id: str | None,
    ) -> Paper:
        """更新 Paper 记录为完成状态.

        Args:
            paper_id: Paper ID
            extraction_result: 提取结果
            fact_check_result: 核查结果
            retry_count: 重试次数

        Returns:
            Paper: 更新后的 Paper 对象
        """
        from datetime import datetime

        update_data = {
            "extraction_status": ExtractionStatus.COMPLETED,
            "quick_scan": json.dumps(
                extraction_result.quick_scan.model_dump(), ensure_ascii=False
            ),
            "synthesis_data": json.dumps(
                extraction_result.synthesis_data.model_dump(), ensure_ascii=False
            ),
            "fact_check_status": (
                FactCheckStatus.PASSED
                if fact_check_result.is_passed
                else FactCheckStatus.FAILED
            ),
            "fact_check_result": json.dumps(
                fact_check_result.model_dump(), ensure_ascii=False
            ),
            "final_fact_check_trace_id": final_fact_check_trace_id,
            "extraction_retry_count": retry_count,
            "updated_at": datetime.now(),
        }

        if not fact_check_result.is_passed:
            logger.warning(
                "event=paper.fact_check_failed paper_id=%s retries=%s",
                paper_id,
                retry_count,
            )

        self.db.update(
            table="papers",
            data=update_data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

        # 重新获取更新后的记录
        row = self.db.fetchone(
            "SELECT * FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        if row is None:
            raise PaperServiceError(
                f"Paper {paper_id} not found after update",
                paper_id=paper_id,
            )
        return Paper.from_db_row(row)

    def _update_paper_with_parse_result(
        self,
        paper_id: str,
        md_content: str,
        images_paths: list[str],
    ) -> None:
        """更新 Paper 记录中的解析产物，并置为 PROCESSING。"""
        self.db.update(
            table="papers",
            data={
                "md_content": md_content,
                "images_paths": json.dumps(images_paths, ensure_ascii=False),
                "extraction_status": ExtractionStatus.PROCESSING,
                "updated_at": datetime.now(),
            },
            where="paper_id = ?",
            where_params=(paper_id,),
        )

    def _update_paper_status(
        self,
        paper_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
        final_fact_check_trace_id: str | None = None,
    ) -> None:
        """更新 Paper 状态.

        Args:
            paper_id: Paper ID
            status: 新状态
            error_message: 错误信息（可选）
        """
        from datetime import datetime

        update_data = {
            "extraction_status": status,
            "updated_at": datetime.now(),
            "final_fact_check_trace_id": final_fact_check_trace_id,
        }

        # 如果是失败状态，可以存储错误信息到 fact_check_result
        if status == ExtractionStatus.FAILED and error_message:
            import json

            update_data["fact_check_result"] = json.dumps(
                {"error": error_message},
                ensure_ascii=False,
            )

        self.db.update(
            table="papers",
            data=update_data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

    def list_project_papers(
        self,
        project_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> list[Paper]:
        """列出项目的论文.

        Args:
            project_id: 项目 ID
            offset: 分页偏移量
            limit: 每页数量

        Returns:
            list[Paper]: Paper 列表
        """
        rows = self.db.fetchall(
            """
            SELECT * FROM papers
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (project_id, limit, offset),
        )

        return [Paper.from_db_row(row) for row in rows]

    def get_paper(self, paper_id: str) -> Paper | None:
        """获取论文详情.

        Args:
            paper_id: Paper ID

        Returns:
            Paper | None: Paper 对象，不存在时返回 None
        """
        row = self.db.fetchone(
            "SELECT * FROM papers WHERE paper_id = ?",
            (paper_id,),
        )

        if not row:
            return None

        return Paper.from_db_row(row)

    async def process_existing_paper(
        self,
        paper_id: str,
        pdf_path: Path | None = None,
        max_retries: int = 3,
    ) -> Paper:
        """处理已存在的 Paper 记录（执行 Agent 提取）.

        此方法用于对已创建记录的 Paper 执行完整的提取-核查流程。

        Args:
            paper_id: Paper ID
            max_retries: 最大重试次数

        Returns:
            Paper: 处理完成的 Paper 对象

        Raises:
            PaperServiceError: 处理失败时抛出
        """
        # 获取现有记录
        paper = self.get_paper(paper_id)
        if not paper:
            raise PaperServiceError(f"Paper {paper_id} not found")

        if paper.extraction_status == ExtractionStatus.COMPLETED:
            logger.info(
                "event=paper.processing_skipped paper_id=%s reason=already_completed",
                paper_id,
            )
            return paper

        try:
            self._update_paper_status(
                paper_id=paper_id,
                status=ExtractionStatus.PROCESSING,
            )

            md_content, image_paths = await self._prepare_existing_processing_inputs(
                paper_id=paper_id,
                paper=paper,
                pdf_path=pdf_path,
            )

            return await self._run_processing_pipeline(
                paper_id=paper_id,
                md_content=md_content,
                image_paths=image_paths,
                max_retries=max_retries,
            )

        except Exception as e:
            self._raise_processing_error(
                paper_id=paper_id,
                stage="Failed to process paper",
                error=e,
                final_fact_check_trace_id=self.data_processor_group.last_fact_check_trace_id,
            )
