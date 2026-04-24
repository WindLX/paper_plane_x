"""Paper 数据仓库.

封装所有 papers 表和 paper_projects 关联表的数据库访问，
不包含任何业务编排或外部服务调用逻辑。
"""

import json
import logging
from datetime import datetime
from typing import TypeAlias, cast
from uuid import uuid4

from paper_plane_x_backend.models import ExtractionStatus, FactCheckStatus, Paper
from paper_plane_x_backend.services.database import Database

logger = logging.getLogger(__name__)

MetadataPayload: TypeAlias = dict[str, object]


class PaperRepositoryError(Exception):
    """PaperRepository 异常."""

    def __init__(
        self,
        message: str,
        paper_id: str | None = None,
        error_code: str = "bad_request",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.paper_id = paper_id
        self.error_code = error_code


class PaperQueryRepository:
    """Paper 只读查询仓库（Projection / Matrix / Structured Search）。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def fetch_by_path(
        self,
        paper_id: str,
        field_path: str,
    ) -> object:
        """按 Dot-Path 精准读取论文字段切片。"""
        normalized = field_path.strip()
        if not normalized:
            raise PaperRepositoryError("field_path cannot be empty", paper_id=paper_id)

        root, *rest = normalized.split(".")
        if root == "meta":
            return self._fetch_meta_by_path(paper_id=paper_id, rest_path=rest)
        if root == "custom_meta":
            return self._fetch_custom_meta_by_path(paper_id=paper_id, rest_path=rest)

        column_map = {
            "md_content": "md_content",
            "quick_scan": "quick_scan",
            "synthesis_data": "synthesis_data",
            "analysis_report": "analysis_report",
        }
        column = column_map.get(root)
        if column is None:
            raise PaperRepositoryError(
                f"Unsupported field path root: {root}",
                paper_id=paper_id,
            )

        if not rest:
            row = self.db.fetchone(
                f"SELECT {column} AS payload FROM papers WHERE paper_id = ?",
                (paper_id,),
            )
            if row is None:
                raise PaperRepositoryError(
                    f"Paper {paper_id} not found",
                    paper_id=paper_id,
                )
            return self._decode_json_or_value(row.get("payload"))

        json_path = "$." + ".".join(rest)
        row = self.db.fetchone(
            f"SELECT json_extract({column}, ?) AS payload FROM papers WHERE paper_id = ?",
            (json_path, paper_id),
        )
        if row is None:
            raise PaperRepositoryError(
                f"Paper {paper_id} not found",
                paper_id=paper_id,
            )
        return self._decode_json_or_value(row.get("payload"))

    def search_paper(
        self,
        *,
        project_id: str | None,
        condition_group: dict[str, object],
        limit: int,
        offset: int,
    ) -> tuple[list[str], int]:
        """统一搜索：可选 project + 组合条件 + 自动质量过滤。"""
        where_clauses: list[str] = []
        params: list[object] = []

        if project_id:
            where_clauses.append("pp.project_id = ?")
            params.append(project_id)

        group_clause, group_params = self._build_search_group_predicate(condition_group)
        where_clauses.append(group_clause)
        params.extend(group_params)

        status_clause, status_params = self._build_search_status_predicate()
        where_clauses.append(status_clause)
        params.extend(status_params)

        where_sql = ""
        if where_clauses:
            where_sql = " WHERE " + " AND ".join(where_clauses)

        from_sql = " FROM papers p"
        if project_id:
            from_sql += " JOIN paper_projects pp ON pp.paper_id = p.paper_id"

        count_row = self.db.fetchone(
            f"SELECT COUNT(*) AS total{from_sql}{where_sql}",
            tuple(params),
        )
        total = int(count_row.get("total", 0)) if count_row else 0

        rows = self.db.fetchall(
            (
                "SELECT p.paper_id"
                f"{from_sql}{where_sql} "
                "ORDER BY p.created_at DESC, p.paper_id ASC "
                "LIMIT ? OFFSET ?"
            ),
            tuple([*params, limit, offset]),
        )

        return [str(row["paper_id"]) for row in rows], total

    @staticmethod
    def _resolve_search_field_expr(field: str) -> str:
        scalar_map: dict[str, str] = {
            "year": "p.year",
            "meta": (
                "json_object('title', p.title, 'authors', p.authors, 'year', p.year, "
                "'publication', p.publication, 'doi', p.doi, 'custom_meta', p.custom_meta)"
            ),
            "meta.title": "p.title",
            "meta.authors": "p.authors",
            "meta.year": "p.year",
            "meta.publication": "p.publication",
            "meta.doi": "p.doi",
            "meta.custom_meta": "p.custom_meta",
            "md_content": "p.md_content",
            "quick_scan": "p.quick_scan",
            "synthesis_data": "p.synthesis_data",
            "analysis_report": "p.analysis_report",
        }
        if field in scalar_map:
            return scalar_map[field]

        if field.startswith("meta.custom_meta."):
            suffix = field[len("meta.custom_meta.") :]
            return f"json_extract(p.custom_meta, '$.{suffix}')"
        if field.startswith("quick_scan."):
            suffix = field[len("quick_scan.") :]
            return f"json_extract(p.quick_scan, '$.{suffix}')"
        if field.startswith("synthesis_data."):
            suffix = field[len("synthesis_data.") :]
            return f"json_extract(p.synthesis_data, '$.{suffix}')"
        if field.startswith("analysis_report."):
            suffix = field[len("analysis_report.") :]
            return f"json_extract(p.analysis_report, '$.{suffix}')"

        raise PaperRepositoryError(
            f"Unsupported search field: {field}",
            error_code="invalid_field",
        )

    def _build_search_group_predicate(
        self,
        group: dict[str, object],
    ) -> tuple[str, list[object]]:
        logic_raw = str(group.get("logic") or "and").strip().lower()
        if logic_raw not in {"and", "or"}:
            raise PaperRepositoryError(
                "condition_group.logic must be 'and' or 'or'",
                error_code="invalid_condition_group",
            )
        joiner = " AND " if logic_raw == "and" else " OR "

        predicates_raw = group.get("predicates")
        groups_raw = group.get("groups")

        clauses: list[str] = []
        params: list[object] = []

        if isinstance(predicates_raw, list):
            for predicate_item in cast(list[object], predicates_raw):
                if not isinstance(predicate_item, dict):
                    raise PaperRepositoryError(
                        "condition_group.predicates must contain objects",
                        error_code="invalid_condition_group",
                    )
                predicate_dict = cast(dict[str, object], predicate_item)
                field = str(predicate_dict.get("field") or "").strip()
                op = str(predicate_dict.get("op") or "").strip()
                value = predicate_dict.get("value")

                field_expr = self._resolve_search_field_expr(field)
                clause, clause_params = self._build_search_predicate(
                    field_expr=field_expr,
                    op=op,
                    value=value,
                    field=field,
                )
                clauses.append(f"({clause})")
                params.extend(clause_params)
        elif predicates_raw is not None:
            raise PaperRepositoryError(
                "condition_group.predicates must be an array",
                error_code="invalid_condition_group",
            )

        if isinstance(groups_raw, list):
            for subgroup in cast(list[object], groups_raw):
                if not isinstance(subgroup, dict):
                    raise PaperRepositoryError(
                        "condition_group.groups must contain objects",
                        error_code="invalid_condition_group",
                    )
                subgroup_dict = cast(dict[str, object], subgroup)
                sub_clause, sub_params = self._build_search_group_predicate(
                    subgroup_dict
                )
                clauses.append(f"({sub_clause})")
                params.extend(sub_params)
        elif groups_raw is not None:
            raise PaperRepositoryError(
                "condition_group.groups must be an array",
                error_code="invalid_condition_group",
            )

        if not clauses:
            raise PaperRepositoryError(
                "condition_group must contain at least one filter or subgroup",
                error_code="invalid_condition_group",
            )

        return joiner.join(clauses), params

    @staticmethod
    def _build_search_predicate(
        *,
        field_expr: str,
        op: str,
        value: object,
        field: str,
    ) -> tuple[str, list[object]]:
        if op == "contains":
            if not isinstance(value, str) or not value.strip():
                raise PaperRepositoryError(
                    f"Operator 'contains' requires non-empty string value for field: {field}",
                    error_code="invalid_value",
                )
            return f"LOWER(CAST({field_expr} AS TEXT)) LIKE ?", [f"%{value.lower()}%"]

        if op == "between":
            if not isinstance(value, list):
                raise PaperRepositoryError(
                    f"Operator 'between' requires [start, end] for field: {field}",
                    error_code="invalid_value",
                )
            range_value = cast(list[object], value)
            if len(range_value) != 2:
                raise PaperRepositoryError(
                    f"Operator 'between' requires [start, end] for field: {field}",
                    error_code="invalid_value",
                )
            start, end = range_value[0], range_value[1]
            if not isinstance(start, int) or not isinstance(end, int):
                raise PaperRepositoryError(
                    f"Operator 'between' only supports integer range for field: {field}",
                    error_code="invalid_value",
                )
            if start > end:
                start, end = end, start
            return f"{field_expr} BETWEEN ? AND ?", [start, end]

        raise PaperRepositoryError(
            f"Unsupported operator: {op}",
            error_code="invalid_operator",
        )

    @staticmethod
    def _build_search_status_predicate() -> tuple[str, list[object]]:
        return (
            "("
            "p.extraction_status IN (?, ?) AND "
            "p.extraction_fact_check_status IN (?, ?) AND "
            "p.analysis_fact_check_status IN (?, ?)"
            ")",
            [
                ExtractionStatus.COMPLETED.value,
                ExtractionStatus.HUMAN_COMPLETED.value,
                FactCheckStatus.PASSED.value,
                FactCheckStatus.HUMAN_PASSED.value,
                FactCheckStatus.PASSED.value,
                FactCheckStatus.HUMAN_PASSED.value,
            ],
        )

    @staticmethod
    def _decode_json_or_value(value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            raw = value.strip()
            if raw and raw[0] in {"{", "[", '"'}:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return value
            return value
        return value

    def _fetch_meta_by_path(self, *, paper_id: str, rest_path: list[str]) -> object:
        row = self.db.fetchone(
            """
            SELECT
                title,
                authors,
                year,
                publication,
                doi,
                custom_meta,
                raw_pdf_path,
                raw_pdf_sha256
            FROM papers
            WHERE paper_id = ?
            """,
            (paper_id,),
        )
        if row is None:
            raise PaperRepositoryError(
                f"Paper {paper_id} not found",
                paper_id=paper_id,
            )

        authors = row.get("authors")
        if isinstance(authors, str):
            try:
                parsed_authors = json.loads(authors)
                if isinstance(parsed_authors, list):
                    authors = [
                        item
                        for item in cast(list[object], parsed_authors)
                        if isinstance(item, str)
                    ]
                else:
                    authors = []
            except json.JSONDecodeError:
                authors = []

        custom_meta = self._decode_json_or_value(row.get("custom_meta"))

        meta: dict[str, object] = {
            "title": row.get("title"),
            "authors": authors,
            "year": row.get("year"),
            "publication": row.get("publication"),
            "doi": row.get("doi"),
            "custom_meta": custom_meta,
            "raw_pdf_path": row.get("raw_pdf_path"),
            "raw_pdf_sha256": row.get("raw_pdf_sha256"),
        }
        return self._traverse_meta(meta, rest_path)

    def _fetch_custom_meta_by_path(
        self, *, paper_id: str, rest_path: list[str]
    ) -> object:
        row = self.db.fetchone(
            "SELECT custom_meta FROM papers WHERE paper_id = ?",
            (paper_id,),
        )
        if row is None:
            raise PaperRepositoryError(
                f"Paper {paper_id} not found",
                paper_id=paper_id,
            )

        current = self._decode_json_or_value(row.get("custom_meta"))
        if not rest_path:
            return current
        return self._traverse_object(current, rest_path)

    @staticmethod
    def _traverse_object(root: object, rest_path: list[str]) -> object:
        current: object = root
        for part in rest_path:
            if isinstance(current, dict):
                current_dict = cast(dict[str, object], current)
                if part not in current_dict:
                    return None
                current = current_dict[part]
                continue

            if isinstance(current, list):
                current_list = cast(list[object], current)
                try:
                    index = int(part)
                except ValueError:
                    return None
                if index < 0 or index >= len(current_list):
                    return None
                current = current_list[index]
                continue

            return None
        return current

    @staticmethod
    def _traverse_meta(meta: dict[str, object], rest_path: list[str]) -> object:
        if not rest_path:
            return meta
        return PaperQueryRepository._traverse_object(meta, rest_path)


class PaperRepository:
    """Paper 数据访问层."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, paper_id: str) -> Paper | None:
        """获取论文详情."""
        row = self.db.fetchone(
            "SELECT p.* FROM papers p WHERE p.paper_id = ?",
            (paper_id,),
        )
        if not row:
            return None
        return Paper.from_db_row(row)

    def list_all(self, offset: int = 0, limit: int = 20) -> list[Paper]:
        """列出所有论文."""
        rows = self.db.fetchall(
            """
            SELECT p.* FROM papers p
            ORDER BY p.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        return [Paper.from_db_row(row) for row in rows]

    def find_by_pdf_hash(self, *, raw_pdf_sha256: str) -> Paper | None:
        """通过 PDF hash 查找论文."""
        row = self.db.fetchone(
            """
            SELECT p.* FROM papers p
            WHERE p.raw_pdf_sha256 = ?
            ORDER BY p.updated_at DESC
            LIMIT 1
            """,
            (raw_pdf_sha256,),
        )
        if row is None:
            return None
        return Paper.from_db_row(row)

    def create(
        self,
        *,
        paper_id: str | None = None,
        md_content: str = "",
        images_paths: list[str] | None = None,
        raw_pdf_path: str | None = None,
        raw_pdf_sha256: str | None = None,
        extraction_status: ExtractionStatus = ExtractionStatus.PROCESSING,
        metadata: MetadataPayload | None = None,
    ) -> Paper:
        """创建 Paper 数据库记录."""
        pid = paper_id or str(uuid4())
        metadata = metadata or {}
        now = datetime.now()

        def _optional_str(key: str) -> str | None:
            value = metadata.get(key)
            return value if isinstance(value, str) else None

        def _optional_int(key: str) -> int | None:
            value = metadata.get(key)
            return value if isinstance(value, int) else None

        authors_value = metadata.get("authors")
        if isinstance(authors_value, list):
            authors: list[str] = []
            for item in cast(list[object], authors_value):
                if isinstance(item, str):
                    authors.append(item)
        elif isinstance(authors_value, str):
            authors = [a.strip() for a in authors_value.split(",") if a.strip()]
        else:
            authors = []

        paper = Paper(
            paper_id=pid,
            title=_optional_str("title"),
            authors=authors,
            year=_optional_int("year"),
            publication=_optional_str("publication"),
            doi=_optional_str("doi"),
            custom_meta=_optional_str("custom_meta"),
            md_content=md_content,
            raw_pdf_path=raw_pdf_path,
            raw_pdf_sha256=raw_pdf_sha256,
            images_paths=images_paths or [],
            extraction_status=extraction_status,
            quick_scan=None,
            synthesis_data=None,
            analysis_report=None,
            extraction_fact_check_status=FactCheckStatus.PENDING,
            extraction_fact_check_result=None,
            analysis_fact_check_status=FactCheckStatus.PENDING,
            analysis_fact_check_result=None,
            extraction_retry_count=0,
            analysis_retry_count=0,
            created_at=now,
            updated_at=now,
        )

        self.db.insert("papers", paper.to_db_dict())
        logger.info("event=paper.record_created paper_id=%s", pid)
        return paper

    def update(self, paper_id: str, data: dict[str, object]) -> None:
        """通用更新接口."""
        self.db.update(
            table="papers",
            data=data,
            where="paper_id = ?",
            where_params=(paper_id,),
        )

    def set_raw_pdf_source(
        self,
        paper_id: str,
        raw_pdf_path: str,
        raw_pdf_sha256: str | None = None,
    ) -> None:
        """更新 Paper 的原始 PDF 路径与可选 hash."""
        update_data: dict[str, object] = {
            "raw_pdf_path": raw_pdf_path,
            "updated_at": datetime.now(),
        }
        if raw_pdf_sha256 is not None:
            update_data["raw_pdf_sha256"] = raw_pdf_sha256
        self.update(paper_id, update_data)

    def manual_update(
        self,
        *,
        paper_id: str,
        title: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        publication: str | None = None,
        doi: str | None = None,
        custom_meta: str | None = None,
        extraction_status: ExtractionStatus | None = None,
        quick_scan: dict[str, object] | None = None,
        synthesis_data: dict[str, object] | None = None,
        analysis_report: dict[str, object] | None = None,
        extraction_fact_check_status: FactCheckStatus | None = None,
        extraction_fact_check_result: dict[str, object] | None = None,
        analysis_fact_check_status: FactCheckStatus | None = None,
        analysis_fact_check_result: dict[str, object] | None = None,
    ) -> Paper:
        """人工更新 Paper 元数据和处理结果（仅数据库操作）."""
        paper = self.get(paper_id)
        if paper is None:
            raise PaperRepositoryError(f"Paper {paper_id} not found", paper_id=paper_id)

        update_data: dict[str, object] = {"updated_at": datetime.now()}
        if title is not None:
            update_data["title"] = title
        if authors is not None:
            update_data["authors"] = json.dumps(authors, ensure_ascii=False)
        if year is not None:
            update_data["year"] = year
        if publication is not None:
            update_data["publication"] = publication
        if doi is not None:
            update_data["doi"] = doi
        if custom_meta is not None:
            update_data["custom_meta"] = custom_meta
        if extraction_status is not None:
            update_data["extraction_status"] = extraction_status
        if quick_scan is not None:
            update_data["quick_scan"] = json.dumps(quick_scan, ensure_ascii=False)
        if synthesis_data is not None:
            update_data["synthesis_data"] = json.dumps(
                synthesis_data, ensure_ascii=False
            )
        if analysis_report is not None:
            update_data["analysis_report"] = json.dumps(
                analysis_report, ensure_ascii=False
            )
        if extraction_fact_check_status is not None:
            update_data["extraction_fact_check_status"] = extraction_fact_check_status
        if extraction_fact_check_result is not None:
            update_data["extraction_fact_check_result"] = json.dumps(
                extraction_fact_check_result, ensure_ascii=False
            )
        if analysis_fact_check_status is not None:
            update_data["analysis_fact_check_status"] = analysis_fact_check_status
        if analysis_fact_check_result is not None:
            update_data["analysis_fact_check_result"] = json.dumps(
                analysis_fact_check_result, ensure_ascii=False
            )

        self.update(paper_id, update_data)
        updated = self.get(paper_id)
        if updated is None:
            raise PaperRepositoryError(
                f"Paper {paper_id} not found after manual update",
                paper_id=paper_id,
            )
        return updated

    def update_parse_result(
        self,
        paper_id: str,
        md_content: str,
        images_paths: list[str],
    ) -> None:
        """更新解析产物，并置状态为 PROCESSING."""
        self.update(
            paper_id,
            {
                "md_content": md_content,
                "images_paths": json.dumps(images_paths, ensure_ascii=False),
                "extraction_status": ExtractionStatus.PROCESSING,
                "updated_at": datetime.now(),
            },
        )

    def update_status(
        self,
        paper_id: str,
        status: ExtractionStatus,
        error_message: str | None = None,
    ) -> None:
        """更新 Paper 状态."""
        update_data: dict[str, object] = {
            "extraction_status": status,
            "updated_at": datetime.now(),
        }
        if status == ExtractionStatus.FAILED and error_message:
            failure_payload = json.dumps(
                {"error": error_message},
                ensure_ascii=False,
            )
            update_data["extraction_fact_check_result"] = failure_payload
            update_data["analysis_fact_check_result"] = failure_payload
        self.update(paper_id, update_data)

    def link_to_project(self, paper_id: str, project_id: str) -> None:
        """建立 paper 与 project 的多对多关系."""
        self.db.execute(
            """
            INSERT INTO paper_projects (paper_id, project_id)
            VALUES (?, ?)
            ON CONFLICT(paper_id, project_id) DO NOTHING
            """,
            (paper_id, project_id),
        )
        logger.info(
            "event=paper.linked_to_project paper_id=%s project_id=%s",
            paper_id,
            project_id,
        )

    def unlink_from_project(self, paper_id: str, project_id: str) -> None:
        """移除 paper 与 project 的关系."""
        self.db.delete(
            table="paper_projects",
            where="paper_id = ? AND project_id = ?",
            where_params=(paper_id, project_id),
        )
        logger.info(
            "event=paper.unlinked_from_project paper_id=%s project_id=%s",
            paper_id,
            project_id,
        )

    def is_linked(self, paper_id: str, project_id: str) -> bool:
        """检查 paper 是否已关联到 project."""
        row = self.db.fetchone(
            "SELECT 1 FROM paper_projects WHERE paper_id = ? AND project_id = ?",
            (paper_id, project_id),
        )
        return row is not None

    def list_project_ids(self, paper_id: str) -> list[str]:
        """获取 paper 关联的所有 project ID."""
        rows = self.db.fetchall(
            "SELECT project_id FROM paper_projects WHERE paper_id = ?",
            (paper_id,),
        )
        return [str(row["project_id"]) for row in rows]
