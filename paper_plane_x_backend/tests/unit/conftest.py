"""Unit-test helpers."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

LitellmResponseFactory = Callable[..., Any]


@pytest.fixture
def make_litellm_response() -> LitellmResponseFactory:
    """Build a minimal LiteLLM/OpenAI-style response object."""

    def _make_response(
        *,
        content: str | None = None,
        reasoning_content: str | None = None,
        tool_calls: list[Any] | None = None,
        usage: dict[str, Any] | None = None,
        model: str = "test-model",
    ) -> Any:
        message = SimpleNamespace(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage=usage,
            model=model,
        )

    return _make_response


@pytest.fixture
def capture_llm_request(
    monkeypatch: pytest.MonkeyPatch,
    make_litellm_response: LitellmResponseFactory,
) -> dict[str, Any]:
    """Patch LLMClient's LiteLLM call and expose the captured request."""
    captured: dict[str, Any] = {}

    async def fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return make_litellm_response(content="ok")

    monkeypatch.setattr(
        "paper_plane_x_backend.core.agent_runtime.llm_client.acompletion",
        fake_acompletion,
    )
    return captured
