"""DataProcessorAgentGroup behavior tests."""

from typing import Any

import pytest

from paper_plane_x_backend.agents.data_processor import DataProcessorAgentGroup


class _FakeSection:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class _FakeExtractionResult:
    def __init__(self) -> None:
        self.quick_scan = _FakeSection({"quick_summary": "ok"})
        self.synthesis_data = _FakeSection({"review_summary": "ok"})

    def model_dump(self) -> dict[str, Any]:
        return {
            "quick_scan": self.quick_scan.model_dump(),
            "synthesis_data": self.synthesis_data.model_dump(),
        }


class _FakeError:
    def __init__(self) -> None:
        self.field_path = "synthesis_data.methodology.core_logic"
        self.suggestion = "Fix it"


class _FakeFactCheckResult:
    def __init__(self, is_passed: bool) -> None:
        self.is_passed = is_passed
        self.errors = [] if is_passed else [_FakeError()]

    def model_dump(self) -> dict[str, Any]:
        return {
            "is_passed": self.is_passed,
            "errors": [
                {
                    "field_path": e.field_path,
                    "suggestion": e.suggestion,
                }
                for e in self.errors
            ],
        }


class _FakeExtractionAgent:
    runtime_name = "ExtractionAgent"

    def __init__(self) -> None:
        self.last_trace_id = "trace-extraction"

    def reset_memory(self) -> None:
        return

    def append_user_message(self, payload: dict[str, Any]) -> None:
        return

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        return

    def build_user_message(self, md_content: str, images: list[str]) -> dict[str, Any]:
        return {"md_content": md_content, "images": images}

    async def run(self, project_id: str):
        return _FakeExtractionResult()


class _FakeFactCheckAgent:
    runtime_name = "FactCheckAgent"

    def __init__(self, result: Any) -> None:
        self._result = result
        self.last_trace_id = "trace-fact-check"

    def reset_memory(self) -> None:
        return

    def append_user_message(self, payload: dict[str, Any]) -> None:
        return

    def append_assistant_message(self, payload: dict[str, Any], *, name: str) -> None:
        return

    def build_user_message(self, md_content: str, images: list[str]) -> dict[str, Any]:
        return {"md_content": md_content, "images": images}

    async def run(self, project_id: str):
        return self._result


@pytest.mark.asyncio
async def test_group_raises_when_fact_check_result_missing() -> None:
    group = DataProcessorAgentGroup(
        extraction_agent=_FakeExtractionAgent(),
        fact_check_agent=_FakeFactCheckAgent(result=None),
    )

    with pytest.raises(RuntimeError) as exc:
        await group.run_extraction_fact_check_loop(
            project_id="paper-1",
            md_content="# md",
            images=[],
            max_retries=1,
        )

    assert "result is empty" in str(exc.value)


@pytest.mark.asyncio
async def test_group_does_not_raise_when_fact_check_failed_with_result() -> None:
    group = DataProcessorAgentGroup(
        extraction_agent=_FakeExtractionAgent(),
        fact_check_agent=_FakeFactCheckAgent(result=_FakeFactCheckResult(False)),
    )

    extraction, fact_check, retry_count = await group.run_extraction_fact_check_loop(
        project_id="paper-1",
        md_content="# md",
        images=[],
        max_retries=1,
    )

    assert extraction.quick_scan.model_dump()["quick_summary"] == "ok"
    assert fact_check.is_passed is False
    assert retry_count == 1
