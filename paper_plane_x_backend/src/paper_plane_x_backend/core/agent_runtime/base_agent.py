"""Agent 基类实现.

实现可复用的 BaseAgent 框架，支持结构化输出和 ReAct 循环。
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from paper_plane_x_backend.config import LLMConfig, settings
from paper_plane_x_backend.core.agent_runtime.exceptions import (
    AgentExecutionError,
    AgentValidationError,
)
from paper_plane_x_backend.core.agent_runtime.llm_client import LLMClient
from paper_plane_x_backend.core.agent_runtime.memory import MemoryManager
from paper_plane_x_backend.core.agent_runtime.tooling import Tool, ToolRegistry
from paper_plane_x_backend.models import AgentTrace
from paper_plane_x_backend.services import get_db

logger = logging.getLogger(__name__)

AgentMode = Literal["api", "normal"]


class BaseAgent:
    """Agent 基类.

    支持两种模式：
    1) api 模式: 强制结构化输出（通过 LLM generate_structured）
    2) normal 模式: 自由文本输出，可进行工具调用循环
    """

    def __init__(
        self,
        output_schema: type[BaseModel] | None = None,
        mode: AgentMode = "api",
        system_prompt: str | None = None,
        tools: list[Tool] | None = None,
        max_steps: int = 10,
        save_trace: bool = True,
        short_memory_window: int = 50,
        llm_config: LLMConfig | None = None,
        agent_name: str | None = None,
    ):
        if mode == "api" and output_schema is None:
            raise ValueError("output_schema is required when mode='api'")

        self.output_schema = output_schema
        self.mode: AgentMode = mode
        self.max_steps = max_steps
        self.save_trace = save_trace
        self.agent_name = agent_name or self.__class__.__name__
        self.last_trace_id: str | None = None

        self.tool_registry = ToolRegistry()
        if tools:
            for tool in tools:
                self.tool_registry.register(tool)

        config = llm_config or settings.llm
        self.llm = LLMClient.from_config(config)
        self.memory = MemoryManager(
            system_prompt=system_prompt or "",
            short_memory_window=short_memory_window,
            is_vlm=config.is_vlm,
        )

    def _get_output_schema(self) -> type[BaseModel]:
        if self.output_schema is None:
            raise AgentExecutionError(
                message="output_schema is not configured for this agent",
                agent_name=self.agent_name,
            )
        return self.output_schema

    @staticmethod
    def _sanitize_json_string_escapes(raw: str) -> str:
        """修复 JSON 字符串内部非法转义（常见于未转义 LaTeX 反斜杠）。"""
        valid_escape_chars = {'"', "\\", "/", "b", "f", "n", "r", "t", "u"}
        result: list[str] = []
        in_string = False
        idx = 0
        length = len(raw)

        while idx < length:
            ch = raw[idx]

            if not in_string:
                result.append(ch)
                if ch == '"':
                    in_string = True
                idx += 1
                continue

            if ch == '"':
                in_string = False
                result.append(ch)
                idx += 1
                continue

            if ch == "\\":
                if idx + 1 >= length:
                    result.append("\\\\")
                    idx += 1
                    continue

                next_char = raw[idx + 1]
                if next_char in valid_escape_chars:
                    result.append("\\")
                    result.append(next_char)
                    idx += 2
                    continue

                # 对于非法转义（例如 \alpha 的 \a），补一个反斜杠使其成为字面量
                result.append("\\\\")
                idx += 1
                continue

            result.append(ch)
            idx += 1

        return "".join(result)

    @staticmethod
    def _load_json_object_candidate(raw: str) -> dict[str, Any] | None:
        try:
            loaded: Any = json.loads(raw)
        except json.JSONDecodeError:
            sanitized = BaseAgent._sanitize_json_string_escapes(raw)
            if sanitized == raw:
                return None
            logger.debug(
                "event=agent.json_sanitize_applied stage=candidate candidate_length=%s sanitized_length=%s",
                len(raw),
                len(sanitized),
            )
            try:
                loaded = json.loads(sanitized)
            except json.JSONDecodeError:
                logger.debug(
                    "event=agent.json_sanitize_failed stage=candidate candidate_length=%s",
                    len(raw),
                )
                return None
        if isinstance(loaded, dict):
            return cast(dict[str, Any], loaded)
        return None

    def _extract_json_candidates_from_code_fences(self, content: str) -> list[str]:
        fence_pattern = re.compile(r"```([^\n`]*)\n?([\s\S]*?)```")
        json_fences: list[str] = []
        other_fences: list[str] = []

        for match in fence_pattern.finditer(content):
            language = (match.group(1) or "").strip().lower()
            candidate = (match.group(2) or "").strip()
            if not candidate:
                continue
            if language == "json":
                json_fences.append(candidate)
            else:
                other_fences.append(candidate)

        return json_fences + other_fences

    def _extract_json_candidates_from_text(self, content: str) -> list[str]:
        candidates: list[str] = []
        length = len(content)

        for start in range(length):
            if content[start] != "{":
                continue

            depth = 0
            in_string = False
            escaped = False

            for end in range(start, length):
                ch = content[end]

                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue

                if ch == '"':
                    in_string = True
                    continue

                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = content[start : end + 1].strip()
                        if candidate:
                            candidates.append(candidate)
                        break
                    if depth < 0:
                        break

        return candidates

    def _collect_json_object_candidates(
        self, content: str
    ) -> list[tuple[int, dict[str, Any]]]:
        candidates: list[tuple[int, dict[str, Any]]] = []

        raw_candidates: list[str] = []
        raw_candidates.extend(self._extract_json_candidates_from_code_fences(content))
        raw_candidates.extend(self._extract_json_candidates_from_text(content))

        seen_raw: set[str] = set()
        for raw in raw_candidates:
            normalized = raw.strip()
            if not normalized or normalized in seen_raw:
                continue
            seen_raw.add(normalized)

            loaded = self._load_json_object_candidate(normalized)
            if loaded is not None:
                candidates.append((len(normalized), loaded))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates

    def _validate_output(self, content: str) -> BaseModel:
        output_schema = self._get_output_schema()
        original_error: AgentValidationError | None = None

        try:
            direct_loaded = json.loads(content)
            if not isinstance(direct_loaded, dict):
                original_error = AgentValidationError(
                    message="Invalid JSON output: root type must be JSON object",
                    agent_name=self.agent_name,
                    raw_output=content,
                )
            else:
                try:
                    return output_schema.model_validate(direct_loaded)
                except ValidationError as e:
                    original_error = AgentValidationError(
                        message=f"Schema validation failed: {e}",
                        agent_name=self.agent_name,
                        validation_errors=[dict(err) for err in e.errors()],
                        raw_output=content,
                    )
        except json.JSONDecodeError:
            pass

        if original_error is None:
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                original_error = AgentValidationError(
                    message=f"Invalid JSON output: {e}",
                    agent_name=self.agent_name,
                    raw_output=content,
                )

        sanitized = self._sanitize_json_string_escapes(content)
        if sanitized != content:
            logger.debug(
                "event=agent.json_sanitize_applied stage=direct content_length=%s sanitized_length=%s",
                len(content),
                len(sanitized),
            )
            try:
                direct_loaded = json.loads(sanitized)
                if not isinstance(direct_loaded, dict):
                    raise AgentValidationError(
                        message="Invalid JSON output: root type must be JSON object",
                        agent_name=self.agent_name,
                        raw_output=content,
                    )
                try:
                    return output_schema.model_validate(direct_loaded)
                except ValidationError:
                    # 保留最原始顶层错误，不用清洗后的 schema 错误覆盖它。
                    pass
            except json.JSONDecodeError:
                logger.debug(
                    "event=agent.json_sanitize_failed stage=direct content_length=%s",
                    len(content),
                )

        json_candidates = self._collect_json_object_candidates(content)
        if not json_candidates:
            if original_error is not None:
                raise original_error

            raise AgentValidationError(
                message="Invalid JSON output: root type must be JSON object",
                agent_name=self.agent_name,
                raw_output=content,
            )

        last_validation_error: ValidationError | None = None
        try:
            for _, data in json_candidates:
                try:
                    return output_schema.model_validate(data)
                except ValidationError as e:
                    last_validation_error = e

            if last_validation_error is not None:
                if original_error is not None:
                    raise original_error
                raise last_validation_error

            raise AgentValidationError(
                message="Schema validation failed: no valid JSON object candidate",
                agent_name=self.agent_name,
                raw_output=content,
            )
        except ValidationError as e:
            if original_error is not None:
                raise original_error
            raise AgentValidationError(
                message=f"Schema validation failed: {e}",
                agent_name=self.agent_name,
                validation_errors=[dict(err) for err in e.errors()],
                raw_output=content,
            ) from e

    def _save_trace(
        self,
        latest_input_message: dict[str, Any] | None,
        output: str,
        messages: list[dict[str, Any]],
        *,
        llm_model: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        try:
            db = get_db()
            usage = usage or {}
            trace_id = str(uuid4())
            trace = AgentTrace(
                trace_id=trace_id,
                agent_name=self.agent_name,
                latest_input_message=latest_input_message,
                output_message=output,
                message_history=messages,
                llm_model=llm_model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
                usage_payload=usage or None,
                created_at=datetime.now(),
            )
            db.insert("agent_traces", trace.to_db_dict())
            self.last_trace_id = trace_id
        except Exception as e:
            logger.warning(
                "event=agent.trace_save_failed agent=%s error=%s",
                self.agent_name,
                e,
            )

    async def _run_api(self) -> BaseModel:
        logger.info(
            "event=agent.run_started agent=%s mode=api",
            self.agent_name,
        )
        if not self.memory.has_role_message("user"):
            raise AgentExecutionError(
                message="No user message in memory. Append user input before run().",
                agent_name=self.agent_name,
            )
        output_schema = self._get_output_schema()
        last_validation_error: AgentValidationError | None = None

        for step in range(self.max_steps):
            content = ""
            try:
                logger.debug(
                    "event=agent.step_started agent=%s mode=api step=%s max_steps=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                )
                response = await self.llm.generate_structured(
                    messages=self.memory.get_messages(),
                    output_schema=output_schema,
                )
                content = response.content or ""
                if self.save_trace:
                    self._save_trace(
                        latest_input_message=self.memory.get_latest_message(),
                        output=content,
                        messages=self.memory.dump_messages(),
                        llm_model=response.model,
                        usage=response.usage,
                    )

                validated_output = self._validate_output(content)

                self.memory.append_assistant_message(
                    content=content, name=self.agent_name
                )

                logger.info(
                    "event=agent.run_completed agent=%s mode=api step=%s",
                    self.agent_name,
                    step + 1,
                )
                return validated_output
            except AgentValidationError as e:
                last_validation_error = e
                logger.warning(
                    "event=agent.validation_retry agent=%s step=%s max_steps=%s error=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                    e.message,
                )
                if content:
                    self.memory.append_assistant_message(
                        content=content, name=self.agent_name
                    )

                error_detail = e.validation_errors if e.validation_errors else e.message
                self.memory.append_validation_feedback(error_detail)
            except asyncio.CancelledError:
                logger.info(
                    "event=agent.run_canceled agent=%s mode=api step=%s",
                    self.agent_name,
                    step + 1,
                )
                raise
            except Exception as e:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=api step=%s max_steps=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                )
                raise AgentExecutionError(
                    message=f"API mode execution failed: {e}",
                    agent_name=self.agent_name,
                ) from e

        if last_validation_error is not None:
            raise last_validation_error

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.max_steps})",
            agent_name=self.agent_name,
            step_count=self.max_steps,
        )

    async def _run_normal(self) -> str:
        logger.info(
            "event=agent.run_started agent=%s mode=normal",
            self.agent_name,
        )
        if not self.memory.has_role_message("user"):
            raise AgentExecutionError(
                message="No user message in memory. Append user input before run().",
                agent_name=self.agent_name,
            )

        if len(self.tool_registry) == 0:
            response = await self.llm.generate(self.memory.get_messages())
            content = response.content or ""
            if self.save_trace:
                self._save_trace(
                    latest_input_message=self.memory.get_latest_message(),
                    output=content,
                    messages=self.memory.dump_messages(),
                    llm_model=response.model,
                    usage=response.usage,
                )

            self.memory.append_assistant_message(content=content, name=self.agent_name)

            logger.info(
                "event=agent.run_completed agent=%s mode=normal step=1",
                self.agent_name,
            )
            return content

        for step in range(self.max_steps):
            logger.debug(
                "event=agent.step_started agent=%s mode=normal step=%s max_steps=%s",
                self.agent_name,
                step + 1,
                self.max_steps,
            )
            try:
                messages = self.memory.get_messages()
                tools = self.tool_registry.to_openai_format()
                if tools:
                    response = await self.llm.generate_with_tools(messages, tools)
                else:
                    response = await self.llm.generate(messages)
                if self.save_trace:
                    self._save_trace(
                        latest_input_message=self.memory.get_latest_message(),
                        output=response.content or "",
                        messages=self.memory.dump_messages(),
                        llm_model=response.model,
                        usage=response.usage,
                    )

                self.memory.append_assistant_message(
                    content=response.content,
                    name=self.agent_name,
                    tool_calls=response.tool_calls or None,
                )

                if response.tool_calls:
                    logger.debug(
                        "event=agent.tool_calls_received agent=%s step=%s tool_call_count=%s",
                        self.agent_name,
                        step + 1,
                        len(response.tool_calls),
                    )
                    for tc in response.tool_calls:
                        tool_msg = await self.tool_registry.execute_tool_call(tc)
                        self.memory.append_tool_message(tool_msg)
                    continue

                content = response.content
            except asyncio.CancelledError:
                logger.info(
                    "event=agent.run_canceled agent=%s mode=normal step=%s",
                    self.agent_name,
                    step + 1,
                )
                raise
            except Exception as e:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=normal step=%s max_steps=%s",
                    self.agent_name,
                    step + 1,
                    self.max_steps,
                )
                raise AgentExecutionError(
                    message=f"Step execution failed: {e}",
                    agent_name=self.agent_name,
                    step_count=step + 1,
                ) from e

            final_content = content or ""
            logger.info(
                "event=agent.run_completed agent=%s mode=normal step=%s",
                self.agent_name,
                step + 1,
            )
            return final_content

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.max_steps})",
            agent_name=self.agent_name,
            step_count=self.max_steps,
        )

    async def run(self) -> BaseModel | str:
        self.last_trace_id = None
        if self.mode == "api":
            return await self._run_api()
        return await self._run_normal()
