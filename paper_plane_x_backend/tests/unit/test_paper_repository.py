"""PaperRepository tests."""

from datetime import datetime

from paper_plane_x_backend.models import ExtractionStatus, FactCheckStatus, Project
from paper_plane_x_backend.services.paper.repository import (
    PaperQueryRepository,
    PaperRepository,
    PaperRepositoryError,
)


class TestPaperRepository:
    """PaperRepository 测试类。"""

    def test_update_parse_result_serializes_images_paths(self, db) -> None:
        """验证解析结果更新时 images_paths 会被正确序列化并可反序列化读取。"""
        now = datetime.now()
        project = Project(
            project_id="proj-1",
            name="paper-repo-test",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        repo = PaperRepository(db)
        paper = repo.create(extraction_status=ExtractionStatus.PENDING)
        repo.link_to_project(paper.paper_id, project.project_id)

        image_paths = ["/tmp/img-1.png", "/tmp/img-2.png"]
        repo.update_parse_result(
            paper_id=paper.paper_id,
            md_content="# Parsed Markdown",
            images_paths=image_paths,
        )

        updated = repo.get(paper.paper_id)
        assert updated is not None
        assert updated.md_content == "# Parsed Markdown"
        assert updated.images_paths == image_paths
        assert updated.extraction_status.value == "PROCESSING"

    def test_manual_update_serializes_json_fields(self, db) -> None:
        """验证 manual_update 时结构化字段以 JSON 文本写入并可正确反序列化读取。"""
        repo = PaperRepository(db)
        paper = repo.create(extraction_status=ExtractionStatus.PENDING)

        updated = repo.manual_update(
            paper_id=paper.paper_id,
            synthesis_data={"review_summary": "manually edited summary"},
        )

        assert updated.synthesis_data is not None
        assert updated.synthesis_data.get("review_summary") == "manually edited summary"

    def test_list_project_ids_after_link(self, db) -> None:
        """验证 link_to_project 和 list_project_ids 的交互。"""
        repo = PaperRepository(db)
        paper = repo.create()

        repo.link_to_project(paper.paper_id, "proj-a")
        repo.link_to_project(paper.paper_id, "proj-b")
        # 重复 link 应被忽略
        repo.link_to_project(paper.paper_id, "proj-a")

        ids = repo.list_project_ids(paper.paper_id)
        assert sorted(ids) == ["proj-a", "proj-b"]

        assert repo.is_linked(paper.paper_id, "proj-a") is True
        repo.unlink_from_project(paper.paper_id, "proj-a")
        assert repo.is_linked(paper.paper_id, "proj-a") is False
        assert repo.list_project_ids(paper.paper_id) == ["proj-b"]

    def test_fetch_by_path_returns_meta_and_nested_json(self, db) -> None:
        """验证 fetch_by_path 支持 meta 及 JSON 字段的 dot-path。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        paper = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Title A", "authors": ["Alice", "Bob"]},
        )
        write_repo.manual_update(
            paper_id=paper.paper_id,
            quick_scan={"verdict": "include", "reason": "fit"},
            synthesis_data={"review_summary": "summary text"},
        )

        assert query_repo.fetch_by_path(paper.paper_id, "meta.title") == "Title A"
        assert query_repo.fetch_by_path(paper.paper_id, "meta.authors.1") == "Bob"
        assert (
            query_repo.fetch_by_path(paper.paper_id, "quick_scan.verdict") == "include"
        )
        assert (
            query_repo.fetch_by_path(paper.paper_id, "synthesis_data.review_summary")
            == "summary text"
        )

    def test_fetch_by_path_invalid_root_raises(self, db) -> None:
        """验证不支持的 root 会报错。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        paper = write_repo.create(extraction_status=ExtractionStatus.PENDING)

        try:
            query_repo.fetch_by_path(paper.paper_id, "unknown.field")
            raise AssertionError("expected PaperRepositoryError")
        except PaperRepositoryError as exc:
            assert "Unsupported field path root" in str(exc)

    def test_fetch_by_path_supports_deep_custom_meta(self, db) -> None:
        """验证 custom_meta 支持任意层级 dot 访问。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        paper = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={
                "title": "T",
                "custom_meta": '{"source":{"name":"manual","version":2},"tags":["a","b"]}',
            },
        )

        assert (
            query_repo.fetch_by_path(paper.paper_id, "meta.custom_meta.source.name")
            == "manual"
        )
        assert (
            query_repo.fetch_by_path(paper.paper_id, "custom_meta.source.version") == 2
        )
        assert query_repo.fetch_by_path(paper.paper_id, "custom_meta.tags.1") == "b"

    def test_search_paper_filters_with_year_range_and_contains(self, db) -> None:
        """验证统一搜索支持 year 范围 + JSON contains。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        p1 = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Layer2-P1", "year": 2024},
        )
        p2 = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Layer2-P2", "year": 2022},
        )
        write_repo.manual_update(
            paper_id=p1.paper_id,
            quick_scan={"verdict": "推荐精读"},
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )
        write_repo.manual_update(
            paper_id=p2.paper_id,
            quick_scan={"verdict": "跳过"},
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )

        paper_ids, total = query_repo.search_paper(
            project_id=None,
            condition_group={
                "logic": "and",
                "predicates": [
                    {"field": "meta.year", "op": "between", "value": [2023, 2025]},
                    {
                        "field": "quick_scan.verdict",
                        "op": "contains",
                        "value": "推荐",
                    },
                ],
                "groups": [],
            },
            limit=10,
            offset=0,
        )

        assert total == 1
        assert paper_ids == [p1.paper_id]

    def test_search_paper_supports_nested_groups_and_project_scope(self, db) -> None:
        """验证统一搜索支持嵌套条件组和 project 作用域。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        p1 = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Scope-P1", "year": 2024},
            md_content="This paper uses AdamW optimizer.",
        )
        p2 = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Scope-P2", "year": 2021},
            md_content="This paper also uses AdamW optimizer.",
        )
        write_repo.manual_update(
            paper_id=p1.paper_id,
            quick_scan={"verdict": "推荐精读"},
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )
        write_repo.manual_update(
            paper_id=p2.paper_id,
            quick_scan={"verdict": "推荐精读"},
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )

        write_repo.link_to_project(p1.paper_id, "proj-a")

        paper_ids, total = query_repo.search_paper(
            project_id="proj-a",
            condition_group={
                "logic": "or",
                "predicates": [
                    {"field": "meta.year", "op": "between", "value": [2025, 2030]}
                ],
                "groups": [
                    {
                        "logic": "and",
                        "predicates": [
                            {
                                "field": "quick_scan.verdict",
                                "op": "contains",
                                "value": "推荐",
                            },
                            {"field": "md_content", "op": "contains", "value": "adamw"},
                        ],
                        "groups": [],
                    }
                ],
            },
            limit=10,
            offset=0,
        )

        assert total == 1
        assert paper_ids == [p1.paper_id]

    def test_search_paper_auto_filters_unqualified_status(self, db) -> None:
        """验证统一搜索会自动过滤未通过状态的数据。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        passed = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Passed", "year": 2024},
            md_content="Lyapunov constraint",
        )
        pending_fact_check = write_repo.create(
            extraction_status=ExtractionStatus.COMPLETED,
            metadata={"title": "Pending", "year": 2024},
            md_content="Lyapunov constraint",
        )
        failed_extraction = write_repo.create(
            extraction_status=ExtractionStatus.FAILED,
            metadata={"title": "Failed", "year": 2024},
            md_content="Lyapunov constraint",
        )

        write_repo.manual_update(
            paper_id=passed.paper_id,
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.HUMAN_PASSED,
        )
        write_repo.manual_update(
            paper_id=pending_fact_check.paper_id,
            extraction_fact_check_status=FactCheckStatus.PENDING,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )
        write_repo.manual_update(
            paper_id=failed_extraction.paper_id,
            extraction_fact_check_status=FactCheckStatus.PASSED,
            analysis_fact_check_status=FactCheckStatus.PASSED,
        )

        paper_ids, total = query_repo.search_paper(
            project_id=None,
            condition_group={
                "logic": "and",
                "predicates": [
                    {
                        "field": "md_content",
                        "op": "contains",
                        "value": "lyapunov",
                    }
                ],
                "groups": [],
            },
            limit=20,
            offset=0,
        )

        assert total == 1
        assert paper_ids == [passed.paper_id]

    def test_fetch_by_path_keeps_citations(self, db) -> None:
        """验证查询层 fetch_by_path 默认保留 citations 字段。"""
        write_repo = PaperRepository(db)
        query_repo = PaperQueryRepository(db)
        paper = write_repo.create(extraction_status=ExtractionStatus.COMPLETED)
        write_repo.manual_update(
            paper_id=paper.paper_id,
            synthesis_data={
                "methodology": {
                    "innovation": {
                        "text": "核心创新",
                        "citations": [{"quote": "Q1", "anchor": "#1"}],
                    }
                }
            },
        )

        value = query_repo.fetch_by_path(
            paper.paper_id,
            "synthesis_data.methodology.innovation",
        )

        assert isinstance(value, dict)
        assert "citations" in value
        assert value.get("text") == "核心创新"
