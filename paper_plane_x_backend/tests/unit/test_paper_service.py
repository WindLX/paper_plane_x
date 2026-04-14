"""PaperService tests."""

from datetime import datetime

from paper_plane_x_backend.models import FactCheckStatus, Project
from paper_plane_x_backend.services import PaperService


class _FakeSection:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, object]:
        return self._payload


class _FakeExtractionResult:
    def __init__(self) -> None:
        self.quick_scan = _FakeSection({"quick_summary": "ok"})
        self.synthesis_data = _FakeSection({"review_summary": "done"})


class _FakeFactCheckResult:
    is_passed = True

    def model_dump(self) -> dict[str, object]:
        return {"is_passed": True, "errors": []}


class _FakeFactCheckFailedResult:
    is_passed = False

    def model_dump(self) -> dict[str, object]:
        return {
            "is_passed": False,
            "errors": [
                {
                    "field_path": "synthesis_data.methodology.core_logic",
                    "generated_claim": "A",
                    "actual_truth": "B",
                    "suggestion": "Fix",
                }
            ],
        }


class TestPaperService:
    """PaperService 测试类。"""

    def test_update_paper_with_parse_result_serializes_images_paths(self, db) -> None:
        """验证解析结果更新时 images_paths 会被正确序列化并可反序列化读取。"""
        now = datetime.now()
        project = Project(
            project_id="proj-1",
            name="paper-service-test",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        service = PaperService(db)
        paper = service.create_pending_paper_record(project_id=project.project_id)

        image_paths = ["/tmp/img-1.png", "/tmp/img-2.png"]
        service._update_paper_with_parse_result(
            paper_id=paper.paper_id,
            md_content="# Parsed Markdown",
            images_paths=image_paths,
        )

        updated = service.get_paper(paper.paper_id)
        assert updated is not None
        assert updated.md_content == "# Parsed Markdown"
        assert updated.images_paths == image_paths
        assert updated.extraction_status.value == "PROCESSING"

    def test_update_paper_with_extraction_result_serializes_json_fields(
        self, db
    ) -> None:
        """验证提取结果更新时结构化字段以 JSON 文本写入并可正确反序列化读取。"""
        now = datetime.now()
        project = Project(
            project_id="proj-2",
            name="paper-service-test-2",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        service = PaperService(db)
        paper = service.create_pending_paper_record(project_id=project.project_id)

        updated = service._update_paper_with_extraction_result(
            paper_id=paper.paper_id,
            extraction_result=_FakeExtractionResult(),  # type: ignore
            fact_check_result=_FakeFactCheckResult(),  # type: ignore
            retry_count=1,
            final_fact_check_trace_id="trace-1",
        )

        assert updated.quick_scan is not None
        assert updated.synthesis_data is not None
        assert updated.fact_check_result is not None
        assert updated.quick_scan.get("quick_summary") == "ok"
        assert updated.synthesis_data.get("review_summary") == "done"
        assert updated.fact_check_result.get("is_passed") is True

    def test_update_paper_with_extraction_result_marks_failed(self, db) -> None:
        """验证 fact check 有结果但未通过时，状态应为 FAILED。"""
        now = datetime.now()
        project = Project(
            project_id="proj-3",
            name="paper-service-test-3",
            description=None,
            created_at=now,
            updated_at=now,
            operation_logs=[],
        )
        db.insert("projects", project.to_db_dict())

        service = PaperService(db)
        paper = service.create_pending_paper_record(project_id=project.project_id)

        updated = service._update_paper_with_extraction_result(
            paper_id=paper.paper_id,
            extraction_result=_FakeExtractionResult(),  # type: ignore
            fact_check_result=_FakeFactCheckFailedResult(),  # type: ignore
            retry_count=3,
            final_fact_check_trace_id="trace-waiting",
        )

        assert updated.fact_check_status == FactCheckStatus.FAILED
        assert updated.fact_check_result is not None
        assert updated.fact_check_result.get("is_passed") is False
