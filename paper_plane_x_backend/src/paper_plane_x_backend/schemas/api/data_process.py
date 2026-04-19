"""Data process API schemas."""

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from paper_plane_x_backend.models import (
    DataProcessTaskStatus,
    ExtractionStatus,
    FactCheckStatus,
)


class DataProcessRequest(BaseModel):
    """数据处理请求.

    元数据字段通过 multipart/form-data 与上传文件一起提交。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] | None = Field(default=None, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    publication: str | None = Field(default=None, description="发表刊物/会议")
    doi: str | None = Field(default=None, description="DOI")
    custom_meta: str | None = Field(default=None, description="自定义 JSON 字符串")


class DataProcessManualUpdateRequest(BaseModel):
    """人工更新论文元数据与 data-process 结果。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] | None = Field(default=None, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    publication: str | None = Field(default=None, description="发表刊物/会议")
    doi: str | None = Field(default=None, description="DOI")
    custom_meta: str | None = Field(default=None, description="自定义 JSON 字符串")
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
    analysis_report: dict[str, Any] | None = Field(
        default=None,
        description="理论分析报告",
    )
    extraction_fact_check_status: (
        Literal[FactCheckStatus.HUMAN_PASSED, FactCheckStatus.FAILED] | None
    ) = Field(
        default=None,
        description="人工 Extraction 核查状态，仅允许 HUMAN_PASSED 或 FAILED",
    )
    extraction_fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="Extraction 事实核查结果",
    )
    analysis_fact_check_status: (
        Literal[FactCheckStatus.HUMAN_PASSED, FactCheckStatus.FAILED] | None
    ) = Field(
        default=None,
        description="人工 Analysis 核查状态，仅允许 HUMAN_PASSED 或 FAILED",
    )
    analysis_fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="Analysis 事实核查结果",
    )

    @field_validator("custom_meta")
    @classmethod
    def validate_custom_meta_json(cls, value: str | None) -> str | None:
        if value is None:
            return None

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"custom_meta must be valid JSON: {exc.msg}") from exc

        if not isinstance(parsed, dict):
            raise ValueError("custom_meta must be a JSON object")
        return value

    @model_validator(mode="after")
    def validate_has_updates(self) -> "DataProcessManualUpdateRequest":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one field must be provided for manual update")
        return self


class DataProcessSubmitResponse(BaseModel):
    """统一的 data-process 提交响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    task_id: str = Field(..., description="后台任务 ID")
    status: DataProcessTaskStatus = Field(..., description="任务状态")
    paper_id: str | None = Field(default=None, description="论文 ID")
    resource_type: str | None = Field(default=None, description="资源类型，如 paper")
    resource_id: str | None = Field(default=None, description="资源 ID，如 paper_id")
    message: str = Field(..., description="状态说明")


class DataProcessTaskResponse(BaseModel):
    """后台任务响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    task_id: str = Field(..., description="任务 ID")
    paper_id: str = Field(..., description="论文 ID")
    status: DataProcessTaskStatus = Field(..., description="任务状态")
    created_at: datetime = Field(..., description="创建时间")
    started_at: datetime | None = Field(default=None, description="开始执行时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    error: str | None = Field(default=None, description="失败原因")
    retry_of_task_id: str | None = Field(default=None, description="重试来源任务 ID")


class DataProcessTaskListResponse(BaseModel):
    """后台任务列表响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    queued: int = Field(..., description="排队中任务数")
    running: int = Field(..., description="运行中任务数")
    completed: int = Field(..., description="已完成任务数")
    failed: int = Field(..., description="失败任务数")
    canceled: int = Field(..., description="已取消任务数")
    items: list[DataProcessTaskResponse] = Field(..., description="任务列表")
