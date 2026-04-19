"""Agent Core 扩展测试.

补充 BaseAgent/LLMClient/Tool schema 的边界覆盖。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from paper_plane_x_backend.config import LLMConfig
from paper_plane_x_backend.core.agent_runtime import (
    AgentExecutionError,
    AgentValidationError,
    BaseAgent,
    LLMClient,
    LLMResponse,
    MemoryManager,
    ToolRegistry,
    tool,
)
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
    ToolMessage,
)


class ApiOutput(BaseModel):
    value: str


class StrictTwoFieldsOutput(BaseModel):
    value: str
    detail: str


class FakeDB:
    def __init__(self) -> None:
        self.inserts: list[tuple[str, dict[str, Any]]] = []

    def insert(self, table: str, data: dict[str, Any]) -> None:
        self.inserts.append((table, data))


def make_response(
    *,
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=usage,
        model="test-model",
    )


class TestBaseAgentExtended:
    @staticmethod
    async def _run_with_input(
        agent: BaseAgent,
        user_input: dict[str, object],
    ) -> BaseModel | str:
        agent.memory.append_user_message(user_input)
        return await agent.run()

    def test_api_mode_requires_schema(self) -> None:
        with pytest.raises(ValueError, match="output_schema is required"):
            BaseAgent(mode="api")

    @pytest.mark.asyncio
    async def test_api_mode_wraps_non_validation_error(self) -> None:
        agent = BaseAgent(output_schema=ApiOutput, mode="api", save_trace=False)

        async def mock_generate_structured(messages, output_schema, **kwargs):
            raise RuntimeError("llm down")

        agent.llm.generate_structured = mock_generate_structured

        with pytest.raises(AgentExecutionError, match="API mode execution failed"):
            await self._run_with_input(agent, {"x": 1})

    @pytest.mark.asyncio
    async def test_save_trace_success_normal_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = BaseAgent(mode="normal", save_trace=True)

        async def mock_generate(messages, **kwargs):
            return LLMResponse(
                content="ok",
                model="trace-model",
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                    "cache_hit": False,
                },
            )

        fake_db = FakeDB()
        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.base_agent.get_db",
            lambda: fake_db,
        )
        agent.llm.generate = mock_generate

        result = await self._run_with_input(
            agent,
            {"query": "q"},
        )

        assert result == "ok"
        assert len(fake_db.inserts) == 1
        table, payload = fake_db.inserts[0]
        assert table == "agent_traces"
        assert payload["agent_name"] == agent.agent_name
        assert "latest_input_message" in payload
        assert payload["llm_model"] == "trace-model"
        assert payload["prompt_tokens"] == 11
        assert payload["completion_tokens"] == 7
        assert payload["total_tokens"] == 18
        assert "cache_hit" in payload["usage_payload"]
        assert agent.last_trace_id is not None

    @pytest.mark.asyncio
    async def test_tool_argument_json_error_bubbles_to_execution_error(self) -> None:
        @tool()
        def noop() -> str:
            return "ok"

        agent = BaseAgent(mode="normal", tools=[noop], max_steps=1, save_trace=False)

        async def mock_generate_with_tools(messages, tools, **kwargs):
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallMessage(
                        id="c1",
                        type="function",
                        function=ToolCallFunction(
                            name="noop",
                            arguments="{bad-json}",
                        ),
                    )
                ],
            )

        agent.llm.generate_with_tools = mock_generate_with_tools

        with pytest.raises(AgentExecutionError, match="Step execution failed"):
            await self._run_with_input(agent, {"x": 1})

    @pytest.mark.asyncio
    async def test_api_mode_prefers_larger_json_candidate(self) -> None:
        agent = BaseAgent(
            output_schema=StrictTwoFieldsOutput,
            mode="api",
            save_trace=False,
            max_steps=1,
        )

        async def mock_generate_structured(messages, output_schema, **kwargs):
            return LLMResponse(
                content=(
                    'small={"value":"v"}\n' 'large={"value":"v","detail":"use-me"}'
                ),
                model="test-model",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        result = await self._run_with_input(agent, {"q": "x"})
        assert isinstance(result, StrictTwoFieldsOutput)
        assert result.value == "v"
        assert result.detail == "use-me"

    @pytest.mark.asyncio
    async def test_api_mode_rejects_array_root_json(self) -> None:
        agent = BaseAgent(
            output_schema=ApiOutput,
            mode="api",
            save_trace=False,
            max_steps=2,
        )

        call_count = 0

        async def mock_generate_structured(messages, output_schema, **kwargs):
            nonlocal call_count
            call_count += 1
            return LLMResponse(
                content='[{"value": "not-allowed"}]',
                model="test-model",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        with pytest.raises(
            AgentValidationError,
            match="root type must be JSON object",
        ):
            await self._run_with_input(agent, {"q": "x"})
        assert call_count == 2


class TestMemoryManagerExtended:
    def test_short_memory_window_keeps_recent_messages(self) -> None:
        memory = MemoryManager(short_memory_window=2)

        memory.append_user_message({"q": "first"})
        memory.append_assistant_message(content="ok")
        memory.append_user_message({"q": "second"})

        messages = memory.get_messages()

        assert len(messages) == 2
        assert messages[0]["role"] == "assistant"
        assert messages[1]["role"] == "user"

    def test_update_messages_by_role(self) -> None:
        memory = MemoryManager()

        memory.append_user_message({"q": "old"})
        memory.append_assistant_message(content="old assistant")
        memory.append_tool_message(
            ToolMessage(
                role="tool", tool_call_id="t1", name="search", content="old tool"
            )
        )

        memory.update_user_message({"q": "new"})
        memory.update_assistant_message(content="new assistant")
        memory.update_tool_message(
            ToolMessage(
                role="tool", tool_call_id="t1", name="search", content="new tool"
            )
        )

        messages = memory.get_messages()
        assert messages[0]["role"] == "user"
        assert '"q": "new"' in str(messages[0]["content"])
        assert messages[1]["content"] == "new assistant"
        assert messages[2]["content"] == "new tool"

    def test_delete_messages_by_role(self) -> None:
        memory = MemoryManager()

        memory.append_user_message({"q": "u1"})
        memory.append_assistant_message(content="a1")
        memory.append_tool_message(
            ToolMessage(role="tool", tool_call_id="t1", name="search", content="x")
        )

        memory.delete_tool_message()
        memory.delete_assistant_message()
        memory.delete_user_message()

        assert memory.get_messages() == []

    def test_update_delete_raise_when_role_missing(self) -> None:
        memory = MemoryManager()

        with pytest.raises(IndexError):
            memory.delete_user_message()
        with pytest.raises(IndexError):
            memory.update_assistant_message(content="x")

    def test_occurrence_from_end_validation(self) -> None:
        memory = MemoryManager()
        memory.append_user_message({"q": "u1"})

        with pytest.raises(ValueError, match="occurrence_from_end"):
            memory.delete_user_message(occurrence_from_end=0)


class TestLLMClientExtended:
    def test_from_config_maps_fields(self) -> None:
        cfg = LLMConfig(
            model="m1",
            api_key="k1",
            base_url="http://x",
            temperature=0.1,
            max_tokens=12,
            timeout=9.0,
            custom_headers={"X-Test": "1"},
            is_vlm=True,
        )
        client = LLMClient.from_config(cfg)

        assert client.model == "m1"
        assert client.api_key == "k1"
        assert client.base_url == "http://x"
        assert client.temperature == 0.1
        assert client.max_tokens == 12
        assert client.timeout == 9.0
        assert client.custom_headers == {"X-Test": "1"}
        assert client.is_vlm is True

    @pytest.mark.asyncio
    async def test_chat_builds_tool_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return make_response(content="ok")

        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.llm_client.acompletion",
            fake_acompletion,
        )

        client = LLMClient(model="m", api_key="k")
        tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]

        resp = await client.chat(
            messages=[{"role": "user", "content": "hi"}], tools=tools
        )

        assert resp.content == "ok"
        assert captured["tools"] == tools
        assert captured["tool_choice"] == "auto"
        assert captured["api_key"] == "k"

    @pytest.mark.asyncio
    async def test_chat_builds_structured_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return make_response(content='{"value":"v"}')

        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.llm_client.acompletion",
            fake_acompletion,
        )

        client = LLMClient(model="m")
        await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            output_schema=ApiOutput,
            temperature=0.33,
        )

        assert captured["response_format"]["type"] == "json_object"
        assert "schema" in captured["response_format"]
        assert captured["temperature"] == 0.33

    @pytest.mark.asyncio
    async def test_chat_infers_openai_provider_for_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_acompletion(**kwargs):
            captured.update(kwargs)
            return make_response(content="ok")

        monkeypatch.setattr(
            "paper_plane_x_backend.core.agent_runtime.llm_client.acompletion",
            fake_acompletion,
        )

        client = LLMClient(model="deepseek-chat", base_url="https://example.com/v1")
        await client.chat(messages=[{"role": "user", "content": "hi"}])

        assert captured["model"] == "deepseek-chat"
        assert captured["custom_llm_provider"] == "openai"

    def test_parse_response_with_tool_calls(self) -> None:
        client = LLMClient(model="m")
        tc = SimpleNamespace(
            id="id1",
            type="function",
            function=SimpleNamespace(name="sum", arguments='{"a":1}'),
        )
        raw = make_response(content=None, tool_calls=[tc], usage={"total_tokens": 5})

        parsed = client._parse_response(raw)

        assert parsed.content is None
        assert parsed.tool_calls is not None
        assert parsed.tool_calls[0].function.name == "sum"
        assert parsed.usage["total_tokens"] == 5

    @pytest.mark.asyncio
    async def test_tool_registry_execute_tool_call_returns_tool_message(self) -> None:
        @tool()
        def code_runner(language: str, code: str) -> dict[str, str]:
            return {"language": language, "code": code}

        registry = ToolRegistry()
        registry.register(code_runner)

        tool_call = ToolCallMessage(
            id="1",
            function=ToolCallFunction(
                name="code_runner",
                arguments='{"language":"python","code":"print(1)"}',
            ),
        )

        tool_msg = await registry.execute_tool_call(tool_call)

        assert tool_msg.role == "tool"
        assert tool_msg.tool_call_id == "1"
        assert tool_msg.name == "code_runner"
        assert '"language": "python"' in tool_msg.content


class TestToolSchemaExtended:
    def test_tool_schema_for_optional_union_and_collections(self) -> None:
        @tool()
        def complex_tool(
            a: int | None,
            b: str | int,
            c: list[int],
            d: dict[str, int],
        ) -> None:
            return None

        props = complex_tool.parameters["properties"]
        assert props["a"]["type"] == "integer"
        assert props["a"]["nullable"] is True
        assert "anyOf" in props["b"]
        assert props["c"]["type"] == "array"
        assert props["c"]["items"]["type"] == "integer"
        assert props["d"]["type"] == "object"

    def test_tool_schema_ignores_annotated_metadata(self) -> None:
        @tool()
        def annotated_tool(
            query: Annotated[
                str,
                "搜索关键词",
                {"examples": ["llm safety"]},
            ],
        ) -> None:
            return None

        query_schema = annotated_tool.parameters["properties"]["query"]
        assert query_schema["type"] == "string"
        assert "description" not in query_schema
        assert "examples" not in query_schema

    @pytest.mark.asyncio
    async def test_execute_raises_when_function_unbound(self) -> None:
        # 通过装饰器创建后手动清空 function，模拟异常路径
        @tool()
        def t(x: int) -> int:
            return x

        t.function = None

        with pytest.raises(RuntimeError, match="has no bound function"):
            await t.execute(x=1)
