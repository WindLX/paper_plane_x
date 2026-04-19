"""Project API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreateRequest(BaseModel):
    """创建项目请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str | None = Field(default=None, description="项目描述")


class ProjectUpdateRequest(BaseModel):
    """更新项目请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    name: str | None = Field(
        default=None, min_length=1, max_length=200, description="项目名称"
    )
    description: str | None = Field(default=None, description="项目描述")


class ProjectResponse(BaseModel):
    """项目响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str = Field(..., description="项目 ID")
    name: str = Field(..., description="项目名称")
    description: str | None = Field(default=None, description="项目描述")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")


class ProjectListResponse(BaseModel):
    """项目列表响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    items: list[ProjectResponse] = Field(..., description="项目列表")
    total: int = Field(..., description="总数")
    offset: int = Field(..., description="偏移量")
    limit: int = Field(..., description="每页数量")
