"""LLM 客户端封装.

基于 LiteLLM 的统一接口，按能力封装模型调用。
"""

import logging
from typing import Any, Literal, TypeVar

from litellm import acompletion  # pyright: ignore[reportUnknownVariableType]
from pydantic import BaseModel, Field

from paper_plane_x_backend.config import LLMConfig, settings
from paper_plane_x_backend.schemas.agent_io.base import (
    ToolCallFunction,
    ToolCallMessage,
)

logger = logging.getLogger(__name__)

OutputType = TypeVar("OutputType", bound=BaseModel)


class LLMResponse(BaseModel):
    """LLM 响应包装类."""

    content: str | None = None
    tool_calls: list[ToolCallMessage] = Field(default_factory=list)
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


class LLMClient:
    """LLM 客户端.

    封装 LiteLLM 调用，提供统一的异步接口。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        timeout: float = 600.0,
        custom_headers: dict[str, str] | None = None,
        is_vlm: bool = False,
    ):
        self.model = model or settings.LLM.model
        self.api_key = api_key or settings.LLM.api_key
        self.base_url = base_url or settings.LLM.base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.custom_headers = custom_headers or {}
        self.is_vlm = is_vlm

    @classmethod
    def from_config(cls, config: LLMConfig) -> "LLMClient":
        return cls(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            timeout=config.timeout,
            custom_headers=config.custom_headers,
            is_vlm=config.is_vlm,
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        message = response.choices[0].message
        raw_tool_calls = getattr(message, "tool_calls", None)

        tool_calls: list[ToolCallMessage] = []
        if raw_tool_calls:
            tool_calls = [
                ToolCallMessage(
                    id=tc.id,
                    type=tc.type,
                    function=ToolCallFunction(
                        name=tc.function.name,
                        arguments=tc.function.arguments,
                    ),
                )
                for tc in raw_tool_calls
            ]

        usage = dict(response.usage) if getattr(response, "usage", None) else {}
        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            model=getattr(response, "model", None),
            usage=usage,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        output_schema: type[OutputType] | None = None,
        tool_choice: Literal["auto"] = "auto",
        **kwargs: Any,
    ) -> LLMResponse:
        logger.debug(
            "event=llm.request model=%s message_count=%s tool_count=%s structured=%s",
            self.model,
            len(messages),
            0 if tools is None else len(tools),
            output_schema is not None,
        )
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": kwargs.pop("temperature", self.temperature),
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
            "timeout": kwargs.pop("timeout", self.timeout),
            "headers": self.custom_headers or None,
        }

        if tools is not None:
            request["tools"] = tools
            request["tool_choice"] = tool_choice

        if output_schema is not None:
            request["response_format"] = {
                "type": "json_object",
                "schema": output_schema.model_json_schema(),
            }

        request.update(kwargs)
        response = await acompletion(**request)
        parsed = self._parse_response(response)
        logger.debug(
            "event=llm.response model=%s has_content=%s tool_call_count=%s usage=%s",
            parsed.model or self.model,
            bool(parsed.content),
            len(parsed.tool_calls),
            parsed.usage,
        )
        return parsed

    async def generate(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, **kwargs)

    async def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, tools=tools, tool_choice="auto", **kwargs)

    async def generate_structured(
        self,
        messages: list[dict[str, Any]],
        output_schema: type[OutputType],
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.chat(messages, output_schema=output_schema, **kwargs)
