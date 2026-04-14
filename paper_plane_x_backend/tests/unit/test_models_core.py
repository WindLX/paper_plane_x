"""Core model tests."""

import json
from datetime import datetime

from paper_plane_x_backend.models.core import (
    AgentTrace,
    ExtractionStatus,
    FactCheckStatus,
    Paper,
)


def test_paper_from_db_row_parses_enums_and_json_fields() -> None:
    now = datetime.now()
    row = {
        "paper_id": "p1",
        "project_id": "proj1",
        "title": "t",
        "authors": json.dumps(["A", "B"], ensure_ascii=False),
        "year": 2024,
        "venue": "v",
        "doi": "d",
        "md_content": "md",
        "raw_pdf_path": "/tmp/a.pdf",
        "raw_pdf_sha256": "hash-1",
        "images_paths": json.dumps(["/tmp/i.png"], ensure_ascii=False),
        "extraction_status": "COMPLETED",
        "quick_scan": json.dumps({"k": 1}, ensure_ascii=False),
        "synthesis_data": json.dumps({"s": 2}, ensure_ascii=False),
        "fact_check_status": "PASSED",
        "fact_check_result": json.dumps({"ok": True}, ensure_ascii=False),
        "final_fact_check_trace_id": "trace-1",
        "extraction_retry_count": 1,
        "created_at": now,
        "updated_at": now,
    }

    paper = Paper.from_db_row(row)

    assert paper.extraction_status == ExtractionStatus.COMPLETED
    assert paper.fact_check_status == FactCheckStatus.PASSED
    assert paper.authors == ["A", "B"]
    assert paper.images_paths == ["/tmp/i.png"]
    assert paper.quick_scan == {"k": 1}
    assert paper.synthesis_data == {"s": 2}
    assert paper.fact_check_result == {"ok": True}
    assert paper.final_fact_check_trace_id == "trace-1"
    assert paper.raw_pdf_sha256 == "hash-1"


def test_paper_from_db_row_fills_empty_list_defaults() -> None:
    now = datetime.now()
    row = {
        "paper_id": "p2",
        "project_id": "proj1",
        "title": None,
        "authors": None,
        "year": None,
        "venue": None,
        "doi": None,
        "md_content": None,
        "raw_pdf_path": None,
        "raw_pdf_sha256": None,
        "images_paths": None,
        "extraction_status": "PENDING",
        "quick_scan": None,
        "synthesis_data": None,
        "fact_check_status": "PENDING",
        "fact_check_result": None,
        "final_fact_check_trace_id": None,
        "extraction_retry_count": 0,
        "created_at": now,
        "updated_at": now,
    }

    paper = Paper.from_db_row(row)

    assert paper.authors == []
    assert paper.images_paths == []


def test_agent_trace_to_db_dict_serializes_json_fields() -> None:
    trace = AgentTrace(
        trace_id="t1",
        project_id="p1",
        agent_name="A",
        latest_input_message={"role": "user", "content": "x"},
        output_message="ok",
        message_history=[{"role": "user", "content": "x"}],
        llm_model="m",
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        usage_payload={"cache_hit": False},
        created_at=datetime.now(),
    )

    payload = trace.to_db_dict()

    assert isinstance(payload["latest_input_message"], str)
    assert isinstance(payload["output_message"], str)
    assert isinstance(payload["message_history"], str)
    assert isinstance(payload["usage_payload"], str)
    assert json.loads(payload["usage_payload"]) == {"cache_hit": False}
