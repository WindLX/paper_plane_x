"""Agent 异常体系.

定义 Agent 执行过程中可能抛出的异常类型。
"""

from typing import Any


class AgentError(Exception):
    """Agent 异常基类."""

    def __init__(self, message: str, agent_name: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.agent_name = agent_name

    def __str__(self) -> str:
        if self.agent_name:
            return f"[{self.agent_name}] {self.message}"
        return self.message


class AgentExecutionError(AgentError):
    """Agent 执行失败异常."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        step_count: int | None = None,
    ) -> None:
        super().__init__(message, agent_name)
        self.step_count = step_count


class AgentValidationError(AgentError):
    """Agent 输出验证失败异常."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        validation_errors: list[dict[str, Any]] | None = None,
        raw_output: str | None = None,
    ) -> None:
        super().__init__(message, agent_name)
        self.validation_errors = validation_errors or []
        self.raw_output = raw_output


class ToolExecutionError(AgentError):
    """工具执行失败异常."""

    def __init__(
        self,
        message: str,
        tool_name: str | None = None,
        tool_args: dict[str, Any] | None = None,
        agent_name: str | None = None,
    ) -> None:
        super().__init__(message, agent_name)
        self.tool_name = tool_name
        self.tool_args = tool_args or {}


class AgentInterruptedError(AgentError):
    """Agent 被中断异常."""

    def __init__(
        self,
        message: str,
        agent_name: str | None = None,
        reason: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, agent_name)
        self.reason = reason
        self.context = context or {}
