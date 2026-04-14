"""API 请求/响应模型.

定义 REST API 的输入输出数据结构。
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    ExtractionStatus,
    FactCheckStatus,
)

# ==================== Project API Schemas ====================


class ProjectCreateRequest(BaseModel):
    """创建项目请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectUpdateRequest(BaseModel):
    """更新项目请求."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="项目名称"
    )
    description: str | None = Field(default=None, description="项目描述")


class ProjectResponse(BaseModel):
    """项目响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    name: str = Field(..., description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class ProjectListResponse(BaseModel):
    """项目列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ProjectResponse] = Field(..., description="项目列表")
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")


# ==================== Error Response ====================


class ErrorResponse(BaseModel):
    """错误响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误信息")
    detail: dict[str, Any] | None = Field(default=None, description="详细错误信息")


# ==================== Common Schemas ====================


class MessageResponse(BaseModel):
    """通用消息响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    message: str = Field(..., description="消息内容")


# ==================== Paper API Schemas ====================


class PaperResponse(BaseModel):
    """论文响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., description="论文 ID")
    project_id: str = Field(..., description="项目 ID")
    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    venue: str | None = Field(default=None, description="发表 venue")
    doi: str | None = Field(default=None, description="DOI")
    raw_pdf_path: str | None = Field(default=None, description="原始 PDF 文件路径")
    raw_pdf_sha256: str | None = Field(
        default=None, description="原始 PDF 的 SHA256 校验值"
    )
    final_fact_check_trace_id: str | None = Field(
        default=None,
        description="提取-核查闭环最终对应的 FactCheckAgent trace_id",
    )
    extraction_status: ExtractionStatus = Field(..., description="提取状态")
    fact_check_status: FactCheckStatus = Field(..., description="核查状态")
    extraction_retry_count: int = Field(default=0, description="重试次数")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class PaperListResponse(BaseModel):
    """论文列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[PaperResponse] = Field(..., description="论文列表")
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")


# ==================== Data Process API Schemas ====================


class DataProcessRequest(BaseModel):
    """数据处理请求.

    元数据字段通过 multipart/form-data 与上传文件一起提交。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] | None = Field(default=None, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    venue: str | None = Field(default=None, description="发表 venue")
    doi: str | None = Field(default=None, description="DOI")


class DataProcessManualUpdateRequest(BaseModel):
    """人工更新论文元数据与 data-process 结果。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] | None = Field(default=None, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    venue: str | None = Field(default=None, description="发表 venue")
    doi: str | None = Field(default=None, description="DOI")
    extraction_status: (
        Literal[ExtractionStatus.HUMAN_COMPLETED, ExtractionStatus.FAILED] | None
    ) = Field(
        default=None,
        description="人工提取状态，仅允许 HUMAN_COMPLETED 或 FAILED",
    )
    quick_scan: dict[str, Any] | None = Field(default=None, description="快速扫描结果")
    synthesis_data: dict[str, Any] | None = Field(
        default=None,
        description="深度综述数据",
    )
    fact_check_status: (
        Literal[FactCheckStatus.HUMAN_PASSED, FactCheckStatus.FAILED] | None
    ) = Field(
        default=None,
        description="人工核查状态，仅允许 HUMAN_PASSED 或 FAILED",
    )
    fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="事实核查结果",
    )

    @model_validator(mode="after")
    def validate_has_updates(self) -> "DataProcessManualUpdateRequest":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one field must be provided for manual update")
        return self


class DataProcessSubmitResponse(BaseModel):
    """统一的 data-process 提交响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    task_id: str = Field(..., description="后台任务 ID")
    status: DataProcessTaskStatus = Field(..., description="任务状态")
    resource_type: str | None = Field(default=None, description="资源类型，如 paper")
    resource_id: str | None = Field(default=None, description="资源 ID，如 paper_id")
    message: str = Field(..., description="状态说明")


class DataProcessTaskResponse(BaseModel):
    """后台任务响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    task_id: str = Field(..., description="任务 ID")
    project_id: str = Field(..., description="项目 ID")
    paper_id: str = Field(..., description="论文 ID")
    status: DataProcessTaskStatus = Field(..., description="任务状态")
    created_at: datetime = Field(..., description="创建时间")
    started_at: datetime | None = Field(default=None, description="开始执行时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    error: str | None = Field(default=None, description="失败原因")
    retry_of_task_id: str | None = Field(default=None, description="重试来源任务 ID")


class DataProcessTaskListResponse(BaseModel):
    """后台任务列表响应."""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    queued: int = Field(..., description="排队中任务数")
    running: int = Field(..., description="运行中任务数")
    completed: int = Field(..., description="已完成任务数")
    failed: int = Field(..., description="失败任务数")
    canceled: int = Field(..., description="已取消任务数")
    items: list[DataProcessTaskResponse] = Field(..., description="任务列表")


class PaperDetailResponse(PaperResponse):
    """论文详情响应（包含提取数据）."""

    quick_scan: dict[str, Any] | None = Field(default=None, description="快速扫描结果")
    synthesis_data: dict[str, Any] | None = Field(
        default=None, description="深度综述数据"
    )
    fact_check_result: dict[str, Any] | None = Field(
        default=None, description="事实核查结果"
    )
