from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- 基础引用结构定义 ---


class Citation(BaseModel):
    """单条原文引用锚点"""

    quote: str = Field(
        ...,
        description="支撑该总结的原文句子（必须是 `raw_md` 中的**精确子串**，绝不允许修改任何标点符号）",
    )
    source_header: str = Field(
        ...,
        description="该片段所在的 Markdown 章节标题（如 '### 3.1 Problem Formulation')",
    )


class CitedText(BaseModel):
    """带引用的复合文本结构"""

    text: str = Field(..., description="AI 提炼总结的文本内容")
    citations: list[Citation] = Field(..., description="支撑该总结的原文引用列表")


# --- Agent Message 结构定义 ---


class ToolCallFunction(BaseModel):
    """函数调用体."""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., description="函数名")
    arguments: str | dict[str, Any] = Field(
        ...,
        description="函数参数，兼容字符串 JSON 与对象两种形式",
    )


class ToolCallMessage(BaseModel):
    """工具调用描述."""

    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(..., description="工具调用唯一 ID")
    type: Literal["function"] = Field(default="function", description="调用类型")
    function: ToolCallFunction = Field(
        ...,
        description="函数调用信息，包含 name 和 arguments",
    )


class SystemMessage(BaseModel):
    """系统消息（Long Memory）."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["system"] = "system"
    content: str = Field(..., description="系统提示词")


class UserMessage(BaseModel):
    """用户消息."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["user"] = "user"
    content: str | list[dict[str, Any]] = Field(
        ...,
        description="用户输入，支持纯文本或多模态 content parts",
    )


class AssistantMessage(BaseModel):
    """助手消息."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: str | None = Field(default=None, description="助手回复")
    name: str | None = Field(default=None, description="助手名称（可选）")
    tool_calls: list[ToolCallMessage] | None = Field(
        default=None,
        description="工具调用列表（当助手决定调用工具时）",
    )


class ToolMessage(BaseModel):
    """工具执行结果消息."""

    model_config = ConfigDict(strict=True, extra="forbid")

    role: Literal["tool"] = "tool"
    tool_call_id: str = Field(..., description="对应的工具调用 ID")
    name: str = Field(..., description="工具名")
    content: str = Field(..., description="工具执行结果内容")
