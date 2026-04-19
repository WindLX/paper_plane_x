"""Common API schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """错误响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误信息")
    detail: dict[str, Any] | None = Field(default=None, description="详细错误信息")


class MessageResponse(BaseModel):
    """通用消息响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    message: str = Field(..., description="消息内容")
