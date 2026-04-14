"""Agent 测试."""

import pytest
from pydantic import BaseModel, Field

from paper_plane_x_backend.config import LLMConfig
from paper_plane_x_backend.core.agent_runtime import (
    AgentExecutionError,
    AgentValidationError,
    BaseAgent,
    LLMResponse,
    ToolRegistry,
    tool,
)
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
)


class SimpleOutput(BaseModel):
    """简单输出模型."""

    answer: str = Field(..., description="回答内容")


class CalculatorOutput(BaseModel):
    """计算器输出模型."""

    result: float = Field(..., description="计算结果")


class TestBaseAgent:
    """BaseAgent 测试类."""

    @staticmethod
    async def _run_with_input(
        agent: BaseAgent,
        user_input: dict[str, object],
        project_id: str = "unknown",
    ) -> BaseModel | str:
        agent.memory.append_user_message(user_input)
        return await agent.run(project_id=project_id)

    @pytest.mark.asyncio
    async def test_api_mode_simple_agent(self) -> None:
        """测试 api 模式 Agent（结构化输出）."""
        # 创建 Agent
        agent = BaseAgent(
            output_schema=SimpleOutput,
            mode="api",
            max_steps=3,
            save_trace=False,
        )

        # Mock LLM 响应
        async def mock_generate_structured(
            messages, output_schema, **kwargs
        ) -> LLMResponse:
            return LLMResponse(
                content='{"answer": "Hello World"}',
                model="gpt-4o",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        # 运行 Agent
        result = await self._run_with_input(agent, {"question": "Say hello"})

        # 验证结果
        assert isinstance(result, SimpleOutput)
        assert result.answer == "Hello World"

    @pytest.mark.asyncio
    async def test_api_mode_validation_error(self) -> None:
        """测试 api 模式结构化输出验证失败（重试后仍失败）."""
        agent = BaseAgent(
            output_schema=SimpleOutput,
            mode="api",
            max_steps=3,
            save_trace=False,
        )

        call_count = 0

        async def mock_generate_structured(
            messages, output_schema, **kwargs
        ) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            return LLMResponse(
                content="{invalid json}",
                model="gpt-4o",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        with pytest.raises(AgentValidationError):
            await self._run_with_input(agent, {"test": "input"})
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_api_mode_validation_retry_then_success(self) -> None:
        """测试 api 模式在首次校验失败后可重试成功."""
        agent = BaseAgent(
            output_schema=SimpleOutput,
            mode="api",
            max_steps=3,
            save_trace=False,
        )

        call_count = 0

        async def mock_generate_structured(
            messages, output_schema, **kwargs
        ) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(content="{invalid json}", model="gpt-4o", usage={})
            return LLMResponse(
                content='{"answer": "Recovered"}',
                model="gpt-4o",
                usage={},
            )

        agent.llm.generate_structured = mock_generate_structured

        result = await self._run_with_input(agent, {"test": "input"})
        assert isinstance(result, SimpleOutput)
        assert result.answer == "Recovered"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_normal_mode_simple_output(self) -> None:
        """测试 normal 模式无工具时自由输出."""
        agent = BaseAgent(
            mode="normal",
            max_steps=2,
            save_trace=False,
        )

        async def mock_generate(messages, **kwargs) -> LLMResponse:
            return LLMResponse(
                content="plain text reply",
                model="gpt-4o",
                usage={},
            )

        agent.llm.generate = mock_generate

        result = await self._run_with_input(agent, {"test": "input"})
        assert isinstance(result, str)
        assert result == "plain text reply"

    @pytest.mark.asyncio
    async def test_normal_mode_tool_loop(self) -> None:
        """测试 normal 模式工具调用循环."""

        @tool()
        def add(a: int, b: int) -> int:
            """两个数相加."""
            return a + b

        agent = BaseAgent(
            mode="normal",
            tools=[add],
            max_steps=3,
            save_trace=False,
        )

        call_count = 0

        async def mock_generate_with_tools(messages, tools, **kwargs) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallMessage(
                            id="call_1",
                            function=ToolCallFunction(
                                name="add",
                                arguments='{"a": 1, "b": 2}',
                            ),
                        )
                    ],
                    model="gpt-4o",
                    usage={},
                )
            return LLMResponse(content="3", model="gpt-4o", usage={})

        agent.llm.generate_with_tools = mock_generate_with_tools

        result = await self._run_with_input(agent, {"question": "1+2"})
        assert result == "3"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_normal_mode_max_steps_exceeded(self) -> None:
        """测试 normal 模式工具循环步数超限异常."""

        @tool()
        def noop() -> str:
            """返回固定值."""
            return "ok"

        agent = BaseAgent(
            mode="normal",
            tools=[noop],
            max_steps=2,
            save_trace=False,
        )

        async def mock_generate_with_tools(messages, tools, **kwargs) -> LLMResponse:
            return LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallMessage(
                        id="call_loop",
                        function=ToolCallFunction(
                            name="noop",
                            arguments="{}",
                        ),
                    )
                ],
                model="gpt-4o",
                usage={},
            )

        agent.llm.generate_with_tools = mock_generate_with_tools

        with pytest.raises(AgentExecutionError) as exc_info:
            await self._run_with_input(agent, {"test": "input"})

        assert "Exceeded maximum steps" in str(exc_info.value)

    def test_short_memory_window_validation(self) -> None:
        with pytest.raises(ValueError, match="short_memory_window"):
            BaseAgent(mode="normal", short_memory_window=0)

    @pytest.mark.asyncio
    async def test_short_memory_persists_history(self) -> None:
        agent = BaseAgent(mode="normal", save_trace=False)

        calls: list[list[dict[str, object]]] = []

        async def mock_generate(messages, **kwargs) -> LLMResponse:
            calls.append([dict(m) for m in messages])
            return LLMResponse(content="ok")

        agent.llm.generate = mock_generate

        await self._run_with_input(agent, {"q": "first"})
        await self._run_with_input(agent, {"q": "second"})

        # 第二次: first user + first assistant + second user
        assert len(calls) == 2
        assert len(calls[1]) == 3
        assert calls[1][0]["role"] == "user"
        assert calls[1][1]["role"] == "assistant"
        assert calls[1][2]["role"] == "user"

    @pytest.mark.asyncio
    async def test_short_memory_window_limits_history(self) -> None:
        agent = BaseAgent(
            mode="normal",
            save_trace=False,
            short_memory_window=2,
        )

        calls: list[list[dict[str, object]]] = []

        async def mock_generate(messages, **kwargs) -> LLMResponse:
            calls.append([dict(m) for m in messages])
            return LLMResponse(content="ok")

        agent.llm.generate = mock_generate

        await self._run_with_input(agent, {"q": "first"})
        await self._run_with_input(agent, {"q": "second"})

        # 第一次: 仅当前 user
        assert len(calls[0]) == 1
        # 窗口=2 时仅保留最近两条交互消息
        assert len(calls[1]) == 2
        assert calls[1][0]["role"] == "assistant"
        assert calls[1][1]["role"] == "user"

        agent.memory.reset_memory()
        await self._run_with_input(agent, {"q": "third"})
        assert len(calls[2]) == 1

    @pytest.mark.asyncio
    async def test_api_mode_images_are_built_as_content_parts(self) -> None:
        agent = BaseAgent(
            output_schema=SimpleOutput,
            mode="api",
            max_steps=2,
            save_trace=False,
            llm_config=LLMConfig(model="test", is_vlm=True),
        )

        captured_messages: list[dict[str, object]] = []

        async def mock_generate_structured(
            messages, output_schema, **kwargs
        ) -> LLMResponse:
            captured_messages.extend([dict(m) for m in messages])
            return LLMResponse(content='{"answer": "ok"}')

        agent.llm.generate_structured = mock_generate_structured

        await self._run_with_input(
            agent,
            {"query": "describe image", "images": ["YWJj"]},
        )

        assert len(captured_messages) == 1
        user_content = captured_messages[0]["content"]
        assert isinstance(user_content, list)
        assert user_content[0]["type"] == "text"
        assert user_content[1]["type"] == "image_url"
        assert user_content[1]["image_url"]["url"] == "YWJj"

    @pytest.mark.asyncio
    async def test_non_vlm_mode_drops_images_from_plain_json_content(self) -> None:
        agent = BaseAgent(
            output_schema=SimpleOutput,
            mode="api",
            max_steps=2,
            save_trace=False,
            llm_config=LLMConfig(model="test", is_vlm=False),
        )

        captured_messages: list[dict[str, object]] = []

        async def mock_generate_structured(
            messages, output_schema, **kwargs
        ) -> LLMResponse:
            captured_messages.extend([dict(m) for m in messages])
            return LLMResponse(content='{"answer": "ok"}')

        agent.llm.generate_structured = mock_generate_structured

        await self._run_with_input(
            agent,
            {"query": "describe image", "images": ["YWJj"]},
        )

        assert len(captured_messages) == 1
        user_content = captured_messages[0]["content"]
        assert isinstance(user_content, str)
        assert '"images": ["YWJj"]' not in user_content
        assert '"query": "describe image"' in user_content

    @pytest.mark.asyncio
    async def test_normal_mode_content_parts_passthrough(self) -> None:
        agent = BaseAgent(mode="normal", save_trace=False)

        captured_messages: list[dict[str, object]] = []

        async def mock_generate(messages, **kwargs) -> LLMResponse:
            captured_messages.extend([dict(m) for m in messages])
            return LLMResponse(content="ok")

        agent.llm.generate = mock_generate

        content_parts = [
            {"type": "text", "text": "请描述图片"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,AAAA"},
            },
        ]

        await self._run_with_input(agent, {"content": content_parts})

        assert len(captured_messages) == 1
        assert captured_messages[0]["role"] == "user"
        assert captured_messages[0]["content"] == content_parts


class TestToolRegistry:
    """工具注册表测试."""

    def test_register_and_get_tool(self) -> None:
        """测试工具注册和获取."""
        registry = ToolRegistry()

        @tool()
        def test_func(query: str, limit: int = 10) -> list[str]:
            """测试函数."""
            return [f"{query}-{i}" for i in range(limit)]

        registry.register(test_func)

        # 获取工具
        tool_instance = registry.get("test_func")
        assert tool_instance is not None
        assert tool_instance.name == "test_func"

    def test_duplicate_registration(self) -> None:
        """测试重复注册异常."""
        registry = ToolRegistry()

        @tool()
        def test_func() -> None:
            """测试函数."""
            pass

        registry.register(test_func)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(test_func)

    def test_to_openai_format(self) -> None:
        """测试 OpenAI 格式转换."""
        registry = ToolRegistry()

        @tool()
        def search(query: str, limit: int = 10) -> list[dict]:
            """搜索论文."""
            return []

        registry.register(search)

        openai_format = registry.to_openai_format()
        assert len(openai_format) == 1
        assert openai_format[0]["type"] == "function"
        assert openai_format[0]["function"]["name"] == "search"


class TestToolDecorator:
    """工具装饰器测试."""

    def test_sync_function(self) -> None:
        """测试同步函数装饰."""

        @tool()
        def calculate(a: int, b: int) -> int:
            """计算两个数的和."""
            return a + b

        assert calculate.name == "calculate"
        assert "计算两个数的和" in calculate.description
        assert "a" in calculate.parameters["properties"]
        assert "b" in calculate.parameters["properties"]
        assert calculate.parameters["required"] == ["a", "b"]

    def test_optional_params(self) -> None:
        """测试可选参数."""

        @tool()
        def search(query: str, limit: int = 10) -> list[str]:
            """搜索."""
            return []

        # limit 有默认值，不应在 required 中
        assert "query" in search.parameters["required"]
        assert "limit" not in search.parameters["required"]

    @pytest.mark.asyncio
    async def test_async_function(self) -> None:
        """测试异步函数装饰."""

        @tool()
        async def async_fetch(url: str) -> str:
            """异步获取数据."""
            return f"data from {url}"

        result = await async_fetch.execute(url="http://test.com")
        assert result == "data from http://test.com"

    def test_custom_name_and_description(self) -> None:
        """测试自定义名称和描述."""

        @tool(name="custom_search", description="自定义搜索工具")
        def my_func(query: str) -> None:
            """This docstring will be ignored."""
            pass

        assert my_func.name == "custom_search"
        assert my_func.description == "自定义搜索工具"
