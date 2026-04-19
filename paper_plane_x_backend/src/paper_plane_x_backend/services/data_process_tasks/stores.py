"""Data process task state stores."""

import json
from abc import ABC, abstractmethod
from collections.abc import Iterator, MutableMapping
from typing import Any, cast

from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessTaskState,
)
from paper_plane_x_backend.services.database import Database


class DataProcessTaskStateStore(ABC):
    """任务状态存储抽象接口。"""

    @abstractmethod
    def clear(self) -> None:
        """清空状态存储。"""

    @abstractmethod
    def upsert(self, state: DataProcessTaskState) -> None:
        """写入或更新任务状态。"""

    @abstractmethod
    def get(self, task_id: str) -> DataProcessTaskState | None:
        """按 task_id 获取任务状态。"""

    @abstractmethod
    def list(self, paper_id: str | None = None) -> list[DataProcessTaskState]:
        """列出任务状态。"""


class InMemoryDataProcessTaskStateStore(DataProcessTaskStateStore):
    """内存版任务状态存储实现。"""

    def __init__(self) -> None:
        self._states: dict[str, DataProcessTaskState] = {}

    @property
    def states(self) -> dict[str, DataProcessTaskState]:
        return self._states

    def clear(self) -> None:
        self._states.clear()

    def upsert(self, state: DataProcessTaskState) -> None:
        self._states[state.task_id] = state

    def get(self, task_id: str) -> DataProcessTaskState | None:
        return self._states.get(task_id)

    def list(self, paper_id: str | None = None) -> list[DataProcessTaskState]:
        values = list(self._states.values())
        if paper_id is not None:
            values = [state for state in values if state.paper_id == paper_id]
        values.sort(key=lambda state: state.created_at, reverse=True)
        return values


class SQLiteDataProcessTaskStateStore(DataProcessTaskStateStore):
    """SQLite 版任务状态存储实现。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    def clear(self) -> None:
        self._db.execute("DELETE FROM data_process_tasks")

    def upsert(self, state: DataProcessTaskState) -> None:
        payload_json = json.dumps(state.payload, ensure_ascii=False)
        self._db.execute(
            """
            INSERT INTO data_process_tasks (
                task_id, paper_id, payload, status,
                created_at, started_at, finished_at, error, retry_of_task_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                paper_id=excluded.paper_id,
                payload=excluded.payload,
                status=excluded.status,
                created_at=excluded.created_at,
                started_at=excluded.started_at,
                finished_at=excluded.finished_at,
                error=excluded.error,
                retry_of_task_id=excluded.retry_of_task_id
            """,
            (
                state.task_id,
                state.paper_id,
                payload_json,
                state.status.value,
                state.created_at,
                state.started_at,
                state.finished_at,
                state.error,
                state.retry_of_task_id,
            ),
        )

    def get(self, task_id: str) -> DataProcessTaskState | None:
        row = self._db.fetchone(
            "SELECT * FROM data_process_tasks WHERE task_id = ?",
            (task_id,),
        )
        if row is None:
            return None
        return self._row_to_state(row)

    def list(self, paper_id: str | None = None) -> list[DataProcessTaskState]:
        if paper_id is None:
            rows = self._db.fetchall(
                "SELECT * FROM data_process_tasks ORDER BY created_at DESC"
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT * FROM data_process_tasks
                WHERE paper_id = ?
                ORDER BY created_at DESC
                """,
                (paper_id,),
            )
        return [self._row_to_state(row) for row in rows]

    @staticmethod
    def _row_to_state(row: dict[str, Any]) -> DataProcessTaskState:
        payload_raw = row.get("payload")
        payload: dict[str, Any]
        if isinstance(payload_raw, str):
            parsed_payload = json.loads(payload_raw)
            if isinstance(parsed_payload, dict):
                payload = {
                    key: value
                    for key, value in cast(dict[Any, Any], parsed_payload).items()
                    if isinstance(key, str)
                }
            else:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = {
                key: value
                for key, value in cast(dict[Any, Any], payload_raw).items()
                if isinstance(key, str)
            }
        else:
            payload = {}

        paper_id = row.get("paper_id")
        if not isinstance(paper_id, str) or not paper_id:
            payload_paper_id = payload.get("paper_id")
            paper_id = payload_paper_id if isinstance(payload_paper_id, str) else ""

        return DataProcessTaskState(
            task_id=row["task_id"],
            paper_id=paper_id,
            payload=payload,
            status=DataProcessTaskStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            finished_at=row.get("finished_at"),
            error=row.get("error"),
            retry_of_task_id=row.get("retry_of_task_id"),
        )


class TaskStateStoreView(MutableMapping[str, DataProcessTaskState]):
    """面向测试的状态访问视图，兼容 task_states 字典访问。"""

    def __init__(self, store: DataProcessTaskStateStore) -> None:
        self._store = store

    def __getitem__(self, key: str) -> DataProcessTaskState:
        value = self._store.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: DataProcessTaskState) -> None:
        if key != value.task_id:
            raise KeyError("task_id key mismatch")
        self._store.upsert(value)

    def __delitem__(self, key: str) -> None:
        raise NotImplementedError("delete is not supported")

    def __iter__(self) -> Iterator[str]:
        for state in self._store.list():
            yield state.task_id

    def __len__(self) -> int:
        return len(self._store.list())
