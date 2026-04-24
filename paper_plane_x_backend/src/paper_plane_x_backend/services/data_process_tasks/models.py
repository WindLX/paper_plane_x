"""Data process task models."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_plane_x_backend.models import DataProcessTaskStatus


@dataclass(slots=True)
class DataProcessQueueTask:
    task_id: str
    paper_id: str
    payload: dict[str, Any]
    cleanup_path: Path | None = None
    retry_of_task_id: str | None = None


@dataclass(slots=True)
class DataProcessTaskState:
    task_id: str
    paper_id: str
    payload: dict[str, Any]
    status: DataProcessTaskStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    retry_of_task_id: str | None = None
    extraction_trace_ids: list[str] = field(default_factory=list)
    analysis_trace_ids: list[str] = field(default_factory=list)
    extraction_fact_check_trace_ids: list[str] = field(default_factory=list)
    analysis_fact_check_trace_ids: list[str] = field(default_factory=list)
