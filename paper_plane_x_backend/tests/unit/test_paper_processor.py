"""PaperProcessor tests."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from paper_plane_x_backend.models import (
    ExtractionStatus,
    FactCheckStatus,
    Project,
)
from paper_plane_x_backend.services.paper.processor import (
    PaperProcessor,
    PaperProcessorError,
)
from paper_plane_x_backend.services.paper.repository import PaperRepository


class _FakeSection:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, object]:
        return self._payload


class _FakeExtractionResult:
    def __init__(self) -> None:
        self.quick_scan = _FakeSection({"quick_summary": "ok"})
        self.synthesis_data = _FakeSection({"review_summary": "done"})


class _FakeAnalysisResult:
    def __init__(self) -> None:
        self.analysis_report = _FakeSection({"summary": "analysis-ok"})


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
                    "field_path": "analysis_report.derivation_steps",
                    "suggestion": "Fix analysis derivation details",
                }
            ],
        }


class _FakeParserSuccess:
    async def prepare_inputs(  # type: ignore[no-untyped-def]
        self,
        paper_id: str,
        paper,
        pdf_path: Path | None,
        update_parse_result_callback=None,
    ) -> tuple[str, list[Path]]:
        _ = paper_id, paper, pdf_path, update_parse_result_callback
        return "# md", []

    def load_images_base64(self, image_paths: list[Path]) -> list[str]:
        _ = image_paths
        return []


class _FakeParserFail:
    async def prepare_inputs(  # type: ignore[no-untyped-def]
        self,
        paper_id: str,
        paper,
        pdf_path: Path | None,
        update_parse_result_callback=None,
    ) -> tuple[str, list[Path]]:
        _ = paper_id, paper, pdf_path, update_parse_result_callback
        raise RuntimeError("mineru unavailable")

    def load_images_base64(self, image_paths: list[Path]) -> list[str]:
        _ = image_paths
        return []


class _FakeParserCanceled:
    async def prepare_inputs(  # type: ignore[no-untyped-def]
        self,
        paper_id: str,
        paper,
        pdf_path: Path | None,
        update_parse_result_callback=None,
    ) -> tuple[str, list[Path]]:
        _ = paper_id, paper, pdf_path, update_parse_result_callback
        raise asyncio.CancelledError()

    def load_images_base64(self, image_paths: list[Path]) -> list[str]:
        _ = image_paths
        return []


class _FakeAgentGroupSuccess:
    extraction_last_fact_check_trace_id = "trace-extraction-ok"
    analysis_last_fact_check_trace_id = "trace-analysis-ok"

    async def run_parallel_loops(  # type: ignore[no-untyped-def]
        self,
        md_content: str,
        images: list[str],
        max_retries: int,
    ):
        _ = md_content, images, max_retries
        return (
            _FakeExtractionResult(),
            _FakeFactCheckResult(),
            1,
            _FakeAnalysisResult(),
            _FakeFactCheckResult(),
            2,
        )


class _FakeAgentGroupFail:
    extraction_last_fact_check_trace_id = "trace-fail-extraction"
    analysis_last_fact_check_trace_id = "trace-fail-analysis"

    async def run_parallel_loops(  # type: ignore[no-untyped-def]
        self,
        md_content: str,
        images: list[str],
        max_retries: int,
    ):
        _ = md_content, images, max_retries
        raise RuntimeError("should not be called")


class _FakeAgentGroupAnalysisFailed:
    extraction_last_fact_check_trace_id = "trace-extraction-pass"
    analysis_last_fact_check_trace_id = "trace-analysis-fail"

    async def run_parallel_loops(  # type: ignore[no-untyped-def]
        self,
        md_content: str,
        images: list[str],
        max_retries: int,
    ):
        _ = md_content, images, max_retries
        return (
            _FakeExtractionResult(),
            _FakeFactCheckResult(),
            1,
            _FakeAnalysisResult(),
            _FakeFactCheckFailedResult(),
            2,
        )


@pytest.mark.asyncio
async def test_process_success_updates_paper(db) -> None:
    repo = PaperRepository(db)
    now = datetime.now()
    project = Project(
        project_id="proj-processor-1",
        name="processor-test",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())

    paper = repo.create(extraction_status=ExtractionStatus.PENDING)
    repo.link_to_project(paper.paper_id, project.project_id)

    processor = PaperProcessor(
        repo=repo,
        parser=_FakeParserSuccess(),  # type: ignore[arg-type]
        agent_group=_FakeAgentGroupSuccess(),  # type: ignore[arg-type]
    )

    updated = await processor.process(paper.paper_id)

    assert updated.extraction_status == ExtractionStatus.COMPLETED
    assert updated.extraction_fact_check_status == FactCheckStatus.PASSED
    assert updated.analysis_fact_check_status == FactCheckStatus.PASSED
    assert updated.quick_scan is not None
    assert updated.quick_scan.get("quick_summary") == "ok"
    assert updated.analysis_report is not None
    assert updated.analysis_report.get("summary") == "analysis-ok"
    assert updated.extraction_final_fact_check_trace_id == "trace-extraction-ok"
    assert updated.analysis_final_fact_check_trace_id == "trace-analysis-ok"
    assert updated.extraction_retry_count == 1
    assert updated.analysis_retry_count == 2


@pytest.mark.asyncio
async def test_process_failure_marks_failed_and_preserves_trace(db) -> None:
    repo = PaperRepository(db)
    paper = repo.create(extraction_status=ExtractionStatus.PENDING)

    processor = PaperProcessor(
        repo=repo,
        parser=_FakeParserFail(),  # type: ignore[arg-type]
        agent_group=_FakeAgentGroupFail(),  # type: ignore[arg-type]
    )

    with pytest.raises(PaperProcessorError):
        await processor.process(paper.paper_id)

    failed = repo.get(paper.paper_id)
    assert failed is not None
    assert failed.extraction_status == ExtractionStatus.FAILED
    assert failed.extraction_final_fact_check_trace_id == "trace-fail-extraction"
    assert failed.analysis_final_fact_check_trace_id == "trace-fail-analysis"
    assert failed.extraction_fact_check_result is not None
    assert "mineru unavailable" in str(failed.extraction_fact_check_result)


@pytest.mark.asyncio
async def test_process_cancellation_is_propagated(db) -> None:
    repo = PaperRepository(db)
    paper = repo.create(extraction_status=ExtractionStatus.PENDING)

    processor = PaperProcessor(
        repo=repo,
        parser=_FakeParserCanceled(),  # type: ignore[arg-type]
        agent_group=_FakeAgentGroupFail(),  # type: ignore[arg-type]
    )

    with pytest.raises(asyncio.CancelledError):
        await processor.process(paper.paper_id)

    latest = repo.get(paper.paper_id)
    assert latest is not None
    assert latest.extraction_status == ExtractionStatus.PROCESSING


@pytest.mark.asyncio
async def test_process_partial_fact_check_failure_sets_human_completed(db) -> None:
    repo = PaperRepository(db)
    now = datetime.now()
    project = Project(
        project_id="proj-processor-2",
        name="processor-test-partial-fail",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())

    paper = repo.create(extraction_status=ExtractionStatus.PENDING)
    repo.link_to_project(paper.paper_id, project.project_id)

    processor = PaperProcessor(
        repo=repo,
        parser=_FakeParserSuccess(),  # type: ignore[arg-type]
        agent_group=_FakeAgentGroupAnalysisFailed(),  # type: ignore[arg-type]
    )

    updated = await processor.process(paper.paper_id)

    assert updated.extraction_status == ExtractionStatus.HUMAN_COMPLETED
    assert updated.extraction_fact_check_status == FactCheckStatus.PASSED
    assert updated.analysis_fact_check_status == FactCheckStatus.FAILED
    assert updated.extraction_retry_count == 1
    assert updated.analysis_retry_count == 2
    assert updated.extraction_final_fact_check_trace_id == "trace-extraction-pass"
    assert updated.analysis_final_fact_check_trace_id == "trace-analysis-fail"
    assert updated.analysis_fact_check_result is not None
    assert updated.analysis_fact_check_result.get("is_passed") is False
