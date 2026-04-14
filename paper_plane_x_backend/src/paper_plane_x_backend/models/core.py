"""核心数据模型.

数据库实体对应的 Pydantic 模型，用于类型安全和数据验证.
"""

import json
from datetime import datetime
from enum import Enum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field


class ExtractionStatus(str, Enum):
    """论文提取状态枚举。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    HUMAN_COMPLETED = "HUMAN_COMPLETED"
    FAILED = "FAILED"


class FactCheckStatus(str, Enum):
    """事实核查状态枚举。"""

    PENDING = "PENDING"
    PASSED = "PASSED"
    HUMAN_PASSED = "HUMAN_PASSED"
    FAILED = "FAILED"


class DataProcessTaskStatus(str, Enum):
    """后台 data-process 任务状态枚举。"""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELING = "CANCELING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class Project(BaseModel):
    """项目模型.

    Project 是用户管理科研工作流的基本业务单元。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="唯一标识 (UUID)")
    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    operation_logs: list[dict[str, Any]] = Field(
        default_factory=lambda: cast(list[dict[str, Any]], []),
        description="项目级别的核心操作流水",
    )

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Project":
        """从数据库行创建模型实例.

        Args:
            row: 数据库行字典

        Returns:
            Project: 项目模型实例
        """
        data = dict(row)
        # 解析 JSON 字段
        operation_logs = data.get("operation_logs")
        if operation_logs and isinstance(operation_logs, str):
            parsed_logs = json.loads(operation_logs)
            if isinstance(parsed_logs, list):
                parsed_items = cast(list[object], parsed_logs)
                data["operation_logs"] = [
                    item for item in parsed_items if isinstance(item, dict)
                ]
            else:
                data["operation_logs"] = []
        elif isinstance(operation_logs, list):
            raw_items = cast(list[object], operation_logs)
            data["operation_logs"] = [
                item for item in raw_items if isinstance(item, dict)
            ]
        else:
            data["operation_logs"] = []
        return cls.model_validate(data)

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入格式.

        Returns:
            dict: 适合数据库插入的字典
        """
        data = self.model_dump()
        # 序列化 JSON 字段
        if data.get("operation_logs") is not None:
            data["operation_logs"] = json.dumps(
                data["operation_logs"], ensure_ascii=False
            )
        return data


class Paper(BaseModel):
    """论文模型.

    存储解析后的论文数据，对应 Data Process 的各个阶段产物。
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # 基础信息
    paper_id: str = Field(..., description="唯一标识 (UUID)")
    project_id: str = Field(..., description="所属项目 ID")
    title: str | None = Field(default=None, description="论文标题")
    authors: list[str] = Field(default_factory=list, description="作者列表")
    year: int | None = Field(default=None, description="发表年份")
    venue: str | None = Field(default=None, description="发表 venue")
    doi: str | None = Field(default=None, description="DOI")

    # 阶段一: MinerU 解析产物
    md_content: str | None = Field(default=None, description="原始 Markdown 文本")
    raw_pdf_path: str | None = Field(
        default=None,
        description="原始 PDF 文件路径",
    )
    raw_pdf_sha256: str | None = Field(
        default=None,
        description="原始 PDF 的 SHA256 校验值",
    )
    images_paths: list[str] = Field(
        default_factory=list,
        description="提取的图片文件路径列表",
    )

    # 阶段二: Data Extraction 产物 (对应 agent_io.ExtractionAgentOutput)
    extraction_status: ExtractionStatus = Field(
        default=ExtractionStatus.PENDING,
        description="提取状态: PENDING, PROCESSING, COMPLETED, FAILED",
    )
    quick_scan: dict[str, Any] | None = Field(
        default=None,
        description="快速扫描结果 (QuickScan 结构)",
    )
    synthesis_data: dict[str, Any] | None = Field(
        default=None,
        description="深度综述数据 (SynthesisData 结构)",
    )

    # 阶段三: Fact Check 产物 (对应 agent_io.FactCheckAgentOutput)
    fact_check_status: FactCheckStatus = Field(
        default=FactCheckStatus.PENDING,
        description="核查状态: PENDING, PASSED, FAILED",
    )
    fact_check_result: dict[str, Any] | None = Field(
        default=None,
        description="事实核查详细结果 (FactCheckAgentOutput 结构)",
    )
    final_fact_check_trace_id: str | None = Field(
        default=None,
        description="提取-核查闭环最终对应的 FactCheckAgent trace_id",
    )

    # 重试计数
    extraction_retry_count: int = Field(
        default=0,
        description="提取重试次数",
    )

    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    @classmethod
    def from_db_row(cls, row: dict[str, Any]) -> "Paper":
        """从数据库行创建模型实例."""
        data = dict(row)

        # SQLite 返回字符串，需要在 strict 模式下显式转换为枚举
        if isinstance(data.get("extraction_status"), str):
            data["extraction_status"] = ExtractionStatus(data["extraction_status"])
        if isinstance(data.get("fact_check_status"), str):
            data["fact_check_status"] = FactCheckStatus(data["fact_check_status"])

        json_fields = [
            "authors",
            "images_paths",
            "quick_scan",
            "synthesis_data",
            "fact_check_result",
        ]
        for field in json_fields:
            if data.get(field) and isinstance(data[field], str):
                data[field] = json.loads(data[field])
            elif field in ["authors", "images_paths"] and data.get(field) is None:
                data[field] = []  # 确保这两个字段至少是空列表
        return cls.model_validate(data)

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入格式."""
        data = self.model_dump()
        # 序列化 JSON 字段
        json_fields = [
            "authors",
            "images_paths",
            "quick_scan",
            "synthesis_data",
            "fact_check_result",
        ]
        for field in json_fields:
            if data.get(field) is not None:
                data[field] = json.dumps(data[field], ensure_ascii=False)
        return data


class AgentTrace(BaseModel):
    """Agent 执行轨迹模型."""

    model_config = ConfigDict(strict=True, extra="forbid")

    trace_id: str = Field(..., description="唯一标识 (UUID)")
    project_id: str = Field(..., description="所属项目 ID")
    agent_name: str = Field(..., description="Agent 名称")
    latest_input_message: dict[str, Any] | None = Field(
        default=None, description="执行时记忆中的最新消息"
    )
    output_message: str | None = Field(default=None, description="执行输出消息")
    message_history: list[dict[str, Any]] | None = Field(
        default=None, description="完整消息历史"
    )
    llm_model: str | None = Field(default=None, description="本次调用的模型标识")
    prompt_tokens: int | None = Field(default=None, description="输入 token 用量")
    completion_tokens: int | None = Field(default=None, description="输出 token 用量")
    total_tokens: int | None = Field(default=None, description="总 token 用量")
    usage_payload: dict[str, Any] | None = Field(
        default=None,
        description="原始 usage 信息（兼容不同 provider 字段）",
    )
    created_at: datetime = Field(..., description="创建时间")

    def to_db_dict(self) -> dict[str, Any]:
        """转换为数据库插入格式."""
        data = self.model_dump()
        # 序列化 JSON 字段
        for field in [
            "latest_input_message",
            "message_history",
            "usage_payload",
        ]:
            if data.get(field) is not None:
                data[field] = json.dumps(data[field], ensure_ascii=False)
        return data
