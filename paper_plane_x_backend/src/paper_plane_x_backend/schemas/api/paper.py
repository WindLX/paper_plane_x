"""Paper API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from paper_plane_x_backend.models import ExtractionStatus, FactCheckStatus


class PaperResponse(BaseModel):
    """论文响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., description="论文 ID")
    project_ids: list[str] = Field(default_factory=list, description="关联项目 ID 列表")
    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    publication: str | None = Field(default=None, description="发表刊物/会议")
    doi: str | None = Field(default=None, description="DOI")
    custom_meta: str | None = Field(default=None, description="自定义 JSON 字符串")
    raw_pdf_path: str | None = Field(default=None, description="原始 PDF 文件路径")
    raw_pdf_sha256: str | None = Field(
        default=None, description="原始 PDF 的 SHA256 校验值"
    )
    extraction_final_fact_check_trace_id: str | None = Field(
        default=None,
        description="Extraction 分支最终对应的 FactCheckAgent trace_id",
    )
    analysis_final_fact_check_trace_id: str | None = Field(
        default=None,
        description="Analysis 分支最终对应的 FactCheckAgent trace_id",
    )
    extraction_status: ExtractionStatus = Field(..., description="提取状态")
    extraction_fact_check_status: FactCheckStatus = Field(
        ...,
        description="Extraction 分支核查状态",
    )
    analysis_fact_check_status: FactCheckStatus = Field(
        ...,
        description="Analysis 分支核查状态",
    )
    extraction_retry_count: int = Field(
        default=0, description="Extraction 分支重试次数"
    )
    analysis_retry_count: int = Field(default=0, description="Analysis 分支重试次数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class PaperListResponse(BaseModel):
    """论文列表响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[PaperResponse] = Field(..., description="论文列表")
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")


class PaperDetailResponse(PaperResponse):
    """论文详情响应（包含提取数据）。"""

    quick_scan: dict[str, Any] | None = Field(default=None, description="快速扫描结果")
    synthesis_data: dict[str, Any] | None = Field(
        default=None, description="深度综述数据"
    )
    analysis_report: dict[str, Any] | None = Field(
        default=None,
        description="理论分析报告",
    )
    extraction_fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="Extraction 事实核查结果",
    )
    analysis_fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="Analysis 事实核查结果",
    )
