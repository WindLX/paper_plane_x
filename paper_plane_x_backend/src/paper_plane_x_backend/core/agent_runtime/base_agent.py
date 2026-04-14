"""Agent 基类实现.

实现可复用的 BaseAgent 框架，支持结构化输出和 ReAct 循环。
"""

import json
import logging
from datetime import datetime
from typing import Any, Literal
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

        config = llm_config or settings.LLM
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

    def _validate_output(self, content: str) -> BaseModel:
        try:
            data = json.loads(content)
            output_schema = self._get_output_schema()
            return output_schema.model_validate(data)
        except json.JSONDecodeError as e:
            raise AgentValidationError(
                message=f"Invalid JSON output: {e}",
                agent_name=self.agent_name,
                raw_output=content,
            ) from e
        except ValidationError as e:
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
        project_id: str,
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
                project_id=project_id,
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
                "event=agent.trace_save_failed agent=%s project_id=%s error=%s",
                self.agent_name,
                project_id,
                e,
            )

    async def _run_api(self, project_id: str) -> BaseModel:
        logger.info(
            "event=agent.run_started agent=%s mode=api project_id=%s",
            self.agent_name,
            project_id,
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
                        project_id=project_id,
                        llm_model=response.model,
                        usage=response.usage,
                    )

                validated_output = self._validate_output(content)

                self.memory.append_assistant_message(
                    content=content, name=self.agent_name
                )

                logger.info(
                    "event=agent.run_completed agent=%s mode=api project_id=%s step=%s",
                    self.agent_name,
                    project_id,
                    step + 1,
                )
                return validated_output
            except AgentValidationError as e:
                last_validation_error = e
                logger.warning(
                    "event=agent.validation_retry agent=%s project_id=%s step=%s max_steps=%s error=%s",
                    self.agent_name,
                    project_id,
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
            except Exception as e:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=api project_id=%s step=%s max_steps=%s",
                    self.agent_name,
                    project_id,
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

    async def _run_normal(self, project_id: str) -> str:
        logger.info(
            "event=agent.run_started agent=%s mode=normal project_id=%s",
            self.agent_name,
            project_id,
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
                    project_id=project_id,
                    llm_model=response.model,
                    usage=response.usage,
                )

            self.memory.append_assistant_message(content=content, name=self.agent_name)

            logger.info(
                "event=agent.run_completed agent=%s mode=normal project_id=%s step=1",
                self.agent_name,
                project_id,
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
                        project_id=project_id,
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
            except Exception as e:
                logger.exception(
                    "event=agent.run_failed agent=%s mode=normal project_id=%s step=%s max_steps=%s",
                    self.agent_name,
                    project_id,
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
                "event=agent.run_completed agent=%s mode=normal project_id=%s step=%s",
                self.agent_name,
                project_id,
                step + 1,
            )
            return final_content

        raise AgentExecutionError(
            message=f"Exceeded maximum steps ({self.max_steps})",
            agent_name=self.agent_name,
            step_count=self.max_steps,
        )

    async def run(
        self,
        project_id: str = "unknown",
    ) -> BaseModel | str:
        self.last_trace_id = None
        if self.mode == "api":
            return await self._run_api(project_id)
        return await self._run_normal(project_id)
