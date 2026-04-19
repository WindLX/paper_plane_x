"""Agent Memory 组件.

负责管理：
- Long Memory: system prompt
- Short Memory: 跨 run 的最近消息窗口
- 用户输入到 messages 的组装（含可选多模态 part）
"""

import json
from typing import Any, cast

from paper_plane_x_backend.schemas.agent_io.base import (
    AssistantMessage,
    SystemMessage,
    ToolCallMessage,
    ToolMessage,
    UserMessage,
)


class MemoryManager:
    """Agent 记忆管理器."""

    def __init__(
        self,
        *,
        system_prompt: str = "",
        short_memory_window: int = 50,
        is_vlm: bool = False,
    ) -> None:
        if short_memory_window <= 0:
            raise ValueError("short_memory_window must be greater than 0")

        self.system_prompt = system_prompt
        self.short_memory_window = short_memory_window
        self.is_vlm = is_vlm

        self._messages: list[dict[str, Any]] = []
        self._system_message: dict[str, Any] | None = None
        if self.system_prompt:
            self._system_message = SystemMessage(
                content=self.system_prompt
            ).model_dump()

    def reset_memory(self) -> None:
        self._messages = []

    def get_messages(self) -> list[dict[str, Any]]:
        """获取当前用于 LLM 调用的消息（system + 短期记忆窗口）。"""
        interaction_messages = self._messages[-self.short_memory_window :]

        messages: list[dict[str, Any]] = []
        if self._system_message is not None:
            messages.append(dict(self._system_message))
        messages.extend(interaction_messages)
        return messages

    def has_role_message(self, role: str) -> bool:
        """判断当前会话是否存在指定 role 的消息。"""
        return any(message.get("role") == role for message in self._messages)

    def get_latest_message(self) -> dict[str, Any] | None:
        """获取当前会话中的最新一条消息。"""
        if not self._messages:
            return None
        return dict(self._messages[-1])

    def dump_messages(self) -> list[dict[str, Any]]:
        """导出会话消息（用于 trace 持久化）。"""
        return list(self.get_messages())

    def _build_user_content(self, inputs: dict[str, Any]) -> str | list[dict[str, Any]]:
        content = inputs.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return [part for part in cast(list[Any], content) if isinstance(part, dict)]

        images = inputs.get("images")
        if self.is_vlm and isinstance(images, list) and images:
            text_payload = {k: v for k, v in inputs.items() if k != "images"}
            parts: list[dict[str, Any]] = []

            if text_payload:
                parts.append(
                    {
                        "type": "text",
                        "text": json.dumps(text_payload, ensure_ascii=False),
                    }
                )

            for image in cast(list[Any], images):
                if isinstance(image, str) and image:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": image},
                        }
                    )

            return parts

        else:
            # 如果不是 VLM 模式，或者 images 字段不合法，则直接将所有输入作为文本处理
            inputs.pop("images", None)  # 移除 images 字段，避免干扰文本内容
            return json.dumps(inputs, ensure_ascii=False)

    def append_user_message(self, user_input: dict[str, Any]) -> None:
        """追加当前 user 消息。"""
        self._messages.append(
            UserMessage(content=self._build_user_content(user_input)).model_dump()
        )

    def append_assistant_message(
        self,
        content: str | None,
        name: str | None = None,
        tool_calls: list[ToolCallMessage] | None = None,
    ) -> None:
        """追加 assistant 消息。"""
        self._messages.append(
            AssistantMessage(
                content=content, name=name, tool_calls=tool_calls
            ).model_dump(exclude_none=True)
        )

    def append_tool_message(
        self,
        tool_message: ToolMessage,
    ) -> None:
        """追加工具结果消息。"""
        self._messages.append(tool_message.model_dump())

    def append_validation_feedback(
        self,
        error_detail: Any,
    ) -> None:
        """追加校验失败反馈消息，引导模型重试。"""
        self._messages.append(
            UserMessage(
                content=(
                    "Output validation failed. Regenerate JSON and strictly follow schema with exact key names and hierarchy. "
                    "Do not add wrapper keys, do not rename fields, do not move fields to new parents. "
                    "If a field is required, place it at the exact schema path. "
                    f"Validation detail: {error_detail}"
                )
            ).model_dump()
        )

    def _find_message_index_by_role(
        self,
        role: str,
        occurrence_from_end: int,
    ) -> int:
        if occurrence_from_end <= 0:
            raise ValueError("occurrence_from_end must be greater than 0")

        matched = 0
        for index in range(len(self._messages) - 1, -1, -1):
            if self._messages[index].get("role") == role:
                matched += 1
                if matched == occurrence_from_end:
                    return index

        raise IndexError(
            f"No '{role}' message found for occurrence {occurrence_from_end}"
        )

    def delete_user_message(self, occurrence_from_end: int = 1) -> None:
        """删除最近第 N 条 user 消息。"""
        index = self._find_message_index_by_role("user", occurrence_from_end)
        del self._messages[index]

    def delete_assistant_message(self, occurrence_from_end: int = 1) -> None:
        """删除最近第 N 条 assistant 消息。"""
        index = self._find_message_index_by_role("assistant", occurrence_from_end)
        del self._messages[index]

    def delete_tool_message(self, occurrence_from_end: int = 1) -> None:
        """删除最近第 N 条 tool 消息。"""
        index = self._find_message_index_by_role("tool", occurrence_from_end)
        del self._messages[index]

    def update_user_message(
        self,
        user_input: dict[str, Any],
        occurrence_from_end: int = 1,
    ) -> None:
        """修改最近第 N 条 user 消息。"""
        index = self._find_message_index_by_role("user", occurrence_from_end)
        self._messages[index] = UserMessage(
            content=self._build_user_content(user_input)
        ).model_dump()

    def update_assistant_message(
        self,
        content: str | None,
        tool_calls: list[ToolCallMessage] | None = None,
        occurrence_from_end: int = 1,
    ) -> None:
        """修改最近第 N 条 assistant 消息。"""
        index = self._find_message_index_by_role("assistant", occurrence_from_end)
        self._messages[index] = AssistantMessage(
            content=content,
            tool_calls=tool_calls,
        ).model_dump(exclude_none=True)

    def update_tool_message(
        self,
        tool_message: ToolMessage,
        occurrence_from_end: int = 1,
    ) -> None:
        """修改最近第 N 条 tool 消息。"""
        index = self._find_message_index_by_role("tool", occurrence_from_end)
        self._messages[index] = tool_message.model_dump()
