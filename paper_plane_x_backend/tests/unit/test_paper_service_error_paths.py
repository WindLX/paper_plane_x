"""PaperService error-path tests."""

from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from paper_plane_x_backend.agents import DataProcessorAgentGroup
from paper_plane_x_backend.models import Project
from paper_plane_x_backend.services import PaperService
from paper_plane_x_backend.services.paper_service import PaperServiceError


class _FakeGroup:
    def __init__(self, trace_id: str | None = None) -> None:
        self.last_fact_check_trace_id = trace_id


@pytest.mark.asyncio
async def test_process_existing_paper_marks_failed_and_keeps_trace_id(
    db,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """MinerU 解析失败时，existing paper 应标记 FAILED 并保存最后 trace_id。"""
    now = datetime.now()
    project = Project(
        project_id="proj-err",
        name="error-path-test",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())

    service = PaperService(
        db,
        data_processor_group=cast(
            DataProcessorAgentGroup,
            _FakeGroup("trace-fail-1"),
        ),
    )
    paper = service.create_pending_paper_record(project_id=project.project_id)
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    async def fake_parse_pdf(self, pdf_path: Path, paper_id: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("mineru unavailable")

    monkeypatch.setattr(PaperService, "_parse_pdf", fake_parse_pdf)

    with pytest.raises(PaperServiceError):
        await service.process_existing_paper(
            paper_id=paper.paper_id,
            pdf_path=pdf_path,
            max_retries=1,
        )

    updated = service.get_paper(paper.paper_id)
    assert updated is not None
    assert updated.extraction_status.value == "FAILED"
    assert updated.final_fact_check_trace_id == "trace-fail-1"
    assert updated.fact_check_result is not None
    assert "mineru unavailable" in str(updated.fact_check_result)
