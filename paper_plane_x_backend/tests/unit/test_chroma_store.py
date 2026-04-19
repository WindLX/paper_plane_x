"""ChromaStore tests."""

from datetime import datetime

import pytest

pytest.importorskip("chromadb")

from paper_plane_x_backend.models import (  # noqa: E402
    ExtractionStatus,
    FactCheckStatus,
    Paper,
)
from paper_plane_x_backend.services.chroma_store import ChromaStore  # noqa: E402


def _build_paper(
    *,
    paper_id: str,
    project_id: str,
    review_summary: str | None,
) -> Paper:
    now = datetime.now()
    synthesis_data = (
        {"review_summary": review_summary, "research_gaps": []}
        if review_summary is not None
        else None
    )
    return Paper(
        paper_id=paper_id,
        title="Test Paper",
        authors=["Alice"],
        year=2024,
        publication=None,
        doi=None,
        custom_meta=None,
        md_content="",
        raw_pdf_path=None,
        raw_pdf_sha256=None,
        images_paths=[],
        extraction_status=ExtractionStatus.COMPLETED,
        quick_scan=None,
        synthesis_data=synthesis_data,
        analysis_report=None,
        extraction_fact_check_status=FactCheckStatus.PASSED,
        extraction_fact_check_result=None,
        extraction_final_fact_check_trace_id=None,
        analysis_fact_check_status=FactCheckStatus.PASSED,
        analysis_fact_check_result=None,
        analysis_final_fact_check_trace_id=None,
        extraction_retry_count=0,
        analysis_retry_count=0,
        created_at=now,
        updated_at=now,
    )


def test_upsert_and_query_by_project(tmp_path) -> None:
    store = ChromaStore(
        enabled=True,
        persist_path=str(tmp_path / "chroma"),
        collection_name="test_collection",
    )

    paper = _build_paper(
        paper_id="paper-1",
        project_id="project-1",
        review_summary="Graph neural networks for molecular discovery",
    )
    assert store.upsert_paper(paper, project_ids=["project-1"]) is True

    rows = store.query_project_papers(
        project_id="project-1",
        query="Graph neural networks for molecular discovery",
        limit=3,
    )

    assert len(rows) >= 1
    assert rows[0]["metadata"]["paper_id"] == "paper-1"


def test_delete_paper_removes_index(tmp_path) -> None:
    store = ChromaStore(
        enabled=True,
        persist_path=str(tmp_path / "chroma"),
        collection_name="test_collection",
    )
    paper = _build_paper(
        paper_id="paper-2",
        project_id="project-2",
        review_summary="A survey on retrieval-augmented generation",
    )
    store.upsert_paper(paper, project_ids=["project-2"])
    assert store.delete_paper(project_id="project-2", paper_id="paper-2") is True

    rows = store.query_project_papers(
        project_id="project-2",
        query="A survey on retrieval-augmented generation",
        limit=3,
    )
    assert rows == []


def test_upsert_skips_empty_summary(tmp_path) -> None:
    store = ChromaStore(
        enabled=True,
        persist_path=str(tmp_path / "chroma"),
        collection_name="test_collection",
    )
    paper = _build_paper(
        paper_id="paper-3",
        project_id="project-3",
        review_summary=None,
    )

    assert store.upsert_paper(paper) is False
