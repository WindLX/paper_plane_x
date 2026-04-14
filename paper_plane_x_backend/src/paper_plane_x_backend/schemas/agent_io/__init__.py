"""Agent I/O schemas."""

from paper_plane_x_backend.schemas.agent_io.base import (
    AssistantMessage,
    Citation,
    CitedText,
    SystemMessage,
    ToolCallMessage,
    UserMessage,
)
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    ExtractionAgentOutput,
    ExtractionAgentUserInput,
    FactCheckAgentOutput,
    FactCheckAgentUserInput,
    FactCheckError,
    KeyResults,
    Methodology,
    QuickScan,
    ResearchGap,
    SynthesisData,
)

__all__ = [
    # Base schemas
    "Citation",
    "CitedText",
    "ToolCallMessage",
    "SystemMessage",
    "UserMessage",
    "AssistantMessage",
    # Data processor schemas
    "QuickScan",
    "ResearchGap",
    "Methodology",
    "KeyResults",
    "SynthesisData",
    "FactCheckError",
    "ExtractionAgentUserInput",
    "ExtractionAgentOutput",
    "FactCheckAgentUserInput",
    "FactCheckAgentOutput",
]
