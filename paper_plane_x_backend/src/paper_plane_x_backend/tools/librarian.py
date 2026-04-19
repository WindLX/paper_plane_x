"""Librarian 工具集合。"""

from __future__ import annotations

from types import UnionType
from typing import Annotated, Any, Union, cast, get_args, get_origin

from pydantic import BaseModel

from paper_plane_x_backend.core.agent_runtime.tooling import tool
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    AnalysisReport,
    QuickScan,
    SynthesisData,
)
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepositoryError,
)


def _strip_citations_recursively(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_citations_recursively(item) for item in cast(list[Any], value)]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, raw in cast(dict[str, Any], value).items():
            if key == "citations":
                continue
            cleaned[key] = _strip_citations_recursively(raw)
        return cleaned
    return value


def matrix_fetch_by_paths(
    *,
    repo: PaperQueryRepository,
    paper_ids: list[str],
    field_paths: list[str],
) -> dict[str, dict[str, Any]]:
    if not paper_ids:
        raise PaperRepositoryError("paper_ids cannot be empty")
    if not field_paths:
        raise PaperRepositoryError("field_paths cannot be empty")

    result: dict[str, dict[str, Any]] = {}
    for paper_id in paper_ids:
        row: dict[str, Any] = {}
        for field_path in field_paths:
            row[field_path] = repo.fetch_by_path(
                paper_id=paper_id,
                field_path=field_path,
            )
        result[paper_id] = row
    return result


def _unwrap_type(annotation: Any) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Annotated and args:
        return _unwrap_type(args[0])

    if origin in (Union, UnionType) and args:
        non_none_types = [arg for arg in args if arg is not type(None)]
        if len(non_none_types) == 1:
            return _unwrap_type(non_none_types[0])

    return annotation


def _collect_model_paths(model_cls: type[BaseModel], root: str) -> list[str]:
    paths: list[str] = [root]

    for field_name, field_info in model_cls.model_fields.items():
        field_path = f"{root}.{field_name}"
        paths.append(field_path)

        annotation = _unwrap_type(field_info.annotation)
        origin = get_origin(annotation)

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(_collect_model_paths(annotation, field_path))
            continue

        if origin is list:
            item_types = get_args(annotation)
            if not item_types:
                continue

            item_type = _unwrap_type(item_types[0])
            list_item_path = f"{field_path}[0]"
            paths.append(list_item_path)

            if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                paths.extend(_collect_model_paths(item_type, list_item_path))

    return paths


def build_field_paths_guide() -> str:
    """构造可复用的 field_paths 说明文本，供多个工具描述复用。"""
    meta_manual_lines = [
        "meta：",
        "- meta：返回整棵元数据对象。",
        "- meta.title / meta.authors / meta.year / meta.publication / meta.doi。",
        "- meta.raw_pdf_path / meta.raw_pdf_sha256。",
        "- meta.custom_meta：返回自定义元数据对象。",
        "- meta.custom_meta.<key>：读取 custom_meta 下的任意键。",
        "- custom_meta 与 custom_meta.<key> 也可直接使用（与 meta.custom_meta 等价）。",
    ]

    structured_roots: list[tuple[str, type[BaseModel]]] = [
        ("quick_scan", QuickScan),
        ("synthesis_data", SynthesisData),
        ("analysis_report", AnalysisReport),
    ]

    structured_sections: list[str] = []
    for root, model_cls in structured_roots:
        structured_sections.append(f"{root}（由 {model_cls.__name__} 自动提取）：")
        for path in _collect_model_paths(model_cls, root):
            structured_sections.append(f"- {path}")

    return "\n".join(
        [
            "可用 field_paths：",
            "- md_content：原始 Markdown 全文。",
            *meta_manual_lines,
            *structured_sections,
            "数组取值规则：使用 [index] 访问元素，例如 analysis_report.prerequisites[0].concept_name。",
        ]
    )


@tool(
    name="matrix_compare",
    description=(
        "用于获取一篇具体论文的某一字段的详细内容，但也支持跨多篇论文按指定字段路径做二维对比，返回 {paper_id -> {field_path -> value}} 结构。"
        "适用场景：需要快速横向比较不同论文在 methodology、results、analysis_report 等字段上的差异。"
        "\n\n输入说明："
        "paper_ids 是论文 ID 列表；field_paths 是点路径列表（如 synthesis_data.methodology.innovation）。"
        "\n\n输出说明："
        "成功时返回 {paper_ids, field_paths, items}，其中 items 为二维矩阵；"
        "失败时返回 {paper_ids, field_paths, error}。"
        "工具会递归剥离 citations 字段以降低上下文体积。"
        "\n\n示例1："
        "paper_ids=['p1','p2'], field_paths=['quick_scan.verdict'] -> items['p1']['quick_scan.verdict']='推荐精读'。"
        "\n\n示例2："
        "paper_ids=['p1','p2'], field_paths=['synthesis_data.methodology.innovation','analysis_report.core_formulation.objective_function']"
        " -> 可直接用于生成方法与理论表述的并排对比草稿。"
        "\n\n" + build_field_paths_guide()
    ),
)
def matrix_compare(
    paper_ids: list[str],
    field_paths: list[str],
) -> dict[str, Any]:
    repo = PaperQueryRepository(get_db())
    try:
        matrix = _strip_citations_recursively(
            matrix_fetch_by_paths(
                repo=repo,
                paper_ids=paper_ids,
                field_paths=field_paths,
            )
        )
    except PaperRepositoryError as exc:
        return {
            "paper_ids": paper_ids,
            "field_paths": field_paths,
            "error": exc.message,
        }
    return {
        "paper_ids": paper_ids,
        "field_paths": field_paths,
        "items": matrix,
    }
