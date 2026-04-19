"""Librarian API schemas."""

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LibrarianProjectionRequest(BaseModel):
    """单 paper 单路径精确投影请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str = Field(..., min_length=1)
    field_path: str = Field(..., min_length=1)


class LibrarianProjectionResponse(BaseModel):
    """单 paper 单路径精确投影响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_id: str
    field_path: str
    value: Any | None = None


class LibrarianMatrixRequest(BaseModel):
    """多 paper 多路径矩阵投影请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_ids: list[str] = Field(..., min_length=1)
    field_paths: list[str] = Field(..., min_length=1)


class LibrarianMatrixResponse(BaseModel):
    """多 paper 多路径矩阵投影响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    paper_ids: list[str]
    field_paths: list[str]
    items: dict[str, dict[str, Any | None]]


class LibrarianConditionPredicate(BaseModel):
    """统一搜索中的原子条件。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    field: str = Field(..., min_length=1, description="过滤字段（projection 路径）")
    op: Literal["contains", "between"] = Field(..., description="操作符")
    value: Any = Field(..., description="过滤值")

    @model_validator(mode="after")
    def validate_predicate(self) -> "LibrarianConditionPredicate":
        normalized = self.field.strip()
        if not normalized:
            raise ValueError("field cannot be empty")

        is_year = normalized in {"year", "meta.year"}
        if is_year:
            if self.op != "between":
                raise ValueError("year only supports 'between' operator")
            raw_value: object = self.value
            if not isinstance(raw_value, list):
                raise ValueError("year 'between' requires [start, end]")
            range_value = cast(list[object], raw_value)
            if len(range_value) != 2:
                raise ValueError("year 'between' requires [start, end]")
            start, end = range_value[0], range_value[1]
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("year 'between' values must be integers")
            return self

        if self.op != "contains":
            raise ValueError("non-year fields only support 'contains' operator")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("contains requires a non-empty string value")
        return self


class LibrarianConditionGroup(BaseModel):
    """统一搜索条件组（支持嵌套 AND/OR）。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    logic: Literal["and", "or"] = Field(default="and", description="组内逻辑")
    predicates: list[LibrarianConditionPredicate] = Field(
        default_factory=lambda: cast(list[LibrarianConditionPredicate], []),
        description="当前组直接包含的原子条件",
    )
    groups: list["LibrarianConditionGroup"] = Field(
        default_factory=lambda: cast(list[LibrarianConditionGroup], []),
        description="子条件组",
    )

    @model_validator(mode="after")
    def validate_group_not_empty(self) -> "LibrarianConditionGroup":
        if not self.predicates and not self.groups:
            raise ValueError("condition group must contain predicates or subgroups")
        return self


class LibrarianUnifiedSearchRequest(BaseModel):
    """统一搜索请求。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str | None = Field(default=None, description="项目作用域，可选")
    condition_group: LibrarianConditionGroup = Field(..., description="组合条件")
    limit: int = Field(default=20, ge=1, le=100, description="返回条数")
    offset: int = Field(default=0, ge=0, description="偏移量")


class LibrarianUnifiedSearchResponse(BaseModel):
    """统一搜索响应。"""

    model_config = ConfigDict(strict=True, extra="forbid")

    project_id: str | None = Field(default=None, description="项目作用域")
    limit: int = Field(..., description="返回条数")
    offset: int = Field(..., description="偏移量")
    total: int = Field(..., description="命中总数")
    paper_ids: list[str] = Field(..., description="命中论文 ID 列表")


LibrarianConditionGroup.model_rebuild()
