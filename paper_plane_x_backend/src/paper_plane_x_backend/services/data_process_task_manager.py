"""Data Process 任务队列管理器。"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services import Database, PaperService, get_db

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DataProcessQueueTask:
    task_id: str
    project_id: str
    payload: dict[str, Any]
    cleanup_path: Path | None = None
    retry_of_task_id: str | None = None


@dataclass(slots=True)
class DataProcessTaskState:
    task_id: str
    project_id: str
    payload: dict[str, Any]
    status: DataProcessTaskStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    retry_of_task_id: str | None = None


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
    def list(self, project_id: str | None = None) -> list[DataProcessTaskState]:
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

    def list(self, project_id: str | None = None) -> list[DataProcessTaskState]:
        values = list(self._states.values())
        if project_id is not None:
            values = [state for state in values if state.project_id == project_id]
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
                task_id, project_id, payload, status,
                created_at, started_at, finished_at, error, retry_of_task_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                project_id=excluded.project_id,
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
                state.project_id,
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

    def list(self, project_id: str | None = None) -> list[DataProcessTaskState]:
        if project_id is None:
            rows = self._db.fetchall(
                "SELECT * FROM data_process_tasks ORDER BY created_at DESC"
            )
        else:
            rows = self._db.fetchall(
                """
                SELECT * FROM data_process_tasks
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            )
        return [self._row_to_state(row) for row in rows]

    @staticmethod
    def _row_to_state(row: dict[str, Any]) -> DataProcessTaskState:
        payload_raw = row.get("payload")
        payload: dict[str, Any]
        if isinstance(payload_raw, str):
            parsed_payload = json.loads(payload_raw)
            payload = parsed_payload if isinstance(parsed_payload, dict) else {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        else:
            payload = {}

        return DataProcessTaskState(
            task_id=row["task_id"],
            project_id=row["project_id"],
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


class DataProcessTaskManager:
    """管理 data-process 后台任务。"""

    def __init__(
        self,
        worker_count: int = 1,
        state_store: DataProcessTaskStateStore | None = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        self.worker_count = max(1, worker_count)
        self._queue: asyncio.Queue[DataProcessQueueTask | None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        if state_store is None:
            db = get_db()
            db.init_tables()
            self._state_store = SQLiteDataProcessTaskStateStore(db)
        else:
            self._state_store = state_store
        self._running_jobs: dict[str, asyncio.Task[object]] = {}
        self._cancel_requests: set[str] = set()
        self._shutdown_timeout = max(0.1, shutdown_timeout)
        self._task_states_view = TaskStateStoreView(self._state_store)

    @property
    def task_states(self) -> MutableMapping[str, DataProcessTaskState]:
        return self._task_states_view

    async def start(self) -> None:
        if self._workers:
            return

        self._running_jobs.clear()
        self._cancel_requests.clear()
        self._queue = asyncio.Queue()
        await self._recover_tasks_on_startup()
        self._workers = [
            asyncio.create_task(
                self._worker_loop(index), name=f"data-process-worker-{index}"
            )
            for index in range(self.worker_count)
        ]
        logger.info(
            "event=task_manager.workers_started worker_count=%s", self.worker_count
        )

    async def _recover_tasks_on_startup(self) -> None:
        if self._queue is None:
            return

        states = self._state_store.list()
        recovered_count = 0
        resumed_count = 0

        for state in states:
            if state.status in {
                DataProcessTaskStatus.RUNNING,
                DataProcessTaskStatus.CANCELING,
            }:
                state.status = DataProcessTaskStatus.QUEUED
                state.started_at = None
                state.finished_at = None
                state.error = None
                self._state_store.upsert(state)

            if state.status == DataProcessTaskStatus.QUEUED:
                await self._queue.put(
                    DataProcessQueueTask(
                        task_id=state.task_id,
                        project_id=state.project_id,
                        payload=state.payload,
                        retry_of_task_id=state.retry_of_task_id,
                    )
                )
                resumed_count += 1

            recovered_count += 1

        if recovered_count:
            logger.info(
                "event=task_manager.tasks_recovered total=%s resumed=%s",
                recovered_count,
                resumed_count,
            )

    async def stop(self) -> None:
        if self._queue is None:
            return

        # 先请求取消正在执行的任务，避免 worker 长时间阻塞在外部调用（例如 LLM 请求）。
        running_jobs = list(self._running_jobs.values())
        for job in running_jobs:
            if not job.done():
                job.cancel()

        if running_jobs:
            await asyncio.gather(*running_jobs, return_exceptions=True)

        queue = self._queue
        workers = list(self._workers)

        for _ in workers:
            await queue.put(None)

        try:
            await asyncio.wait_for(
                asyncio.gather(*workers, return_exceptions=True),
                timeout=self._shutdown_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "event=task_manager.workers_force_stop timeout_seconds=%.1f",
                self._shutdown_timeout,
            )
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

        self._workers = []
        self._queue = None
        self._running_jobs.clear()
        self._cancel_requests.clear()
        logger.info("event=task_manager.workers_stopped")

    async def submit_task(self, task: DataProcessQueueTask) -> DataProcessTaskState:
        if self._queue is None:
            raise RuntimeError("DataProcessTaskManager is not started")
        if self._state_store.get(task.task_id) is not None:
            raise ValueError(f"Task {task.task_id} already exists")

        state = DataProcessTaskState(
            task_id=task.task_id,
            project_id=task.project_id,
            payload=task.payload,
            status=DataProcessTaskStatus.QUEUED,
            created_at=datetime.now(),
            retry_of_task_id=task.retry_of_task_id,
        )
        self._state_store.upsert(state)
        await self._queue.put(task)
        logger.info(
            "event=task_manager.task_submitted task_id=%s project_id=%s paper_id=%s",
            task.task_id,
            task.project_id,
            task.payload.get("paper_id"),
        )
        return state

    def list_tasks(
        self, *, project_id: str | None = None
    ) -> list[DataProcessTaskState]:
        return self._state_store.list(project_id=project_id)

    def get_task(self, task_id: str) -> DataProcessTaskState | None:
        return self._state_store.get(task_id)

    def cancel_task(self, task_id: str) -> DataProcessTaskState:
        state = self._state_store.get(task_id)
        if state is None:
            raise KeyError(task_id)

        if state.status in {
            DataProcessTaskStatus.COMPLETED,
            DataProcessTaskStatus.FAILED,
            DataProcessTaskStatus.CANCELED,
        }:
            raise ValueError(f"Task {task_id} already finished")

        self._cancel_requests.add(task_id)
        if state.status == DataProcessTaskStatus.QUEUED:
            state.status = DataProcessTaskStatus.CANCELED
            state.finished_at = datetime.now()
            logger.info("event=task_manager.task_canceled_queued task_id=%s", task_id)
        else:
            state.status = DataProcessTaskStatus.CANCELING
            running = self._running_jobs.get(task_id)
            if running is not None:
                running.cancel()
            logger.info("event=task_manager.task_cancel_requested task_id=%s", task_id)
        self._state_store.upsert(state)
        return state

    async def _worker_loop(self, worker_id: int) -> None:
        if self._queue is None:
            return

        while True:
            task = await self._queue.get()
            if task is None:
                self._queue.task_done()
                logger.info("event=task_manager.worker_stopped worker_id=%s", worker_id)
                break

            state = self._state_store.get(task.task_id)
            if state is None:
                self._queue.task_done()
                continue

            if task.task_id in self._cancel_requests:
                state.status = DataProcessTaskStatus.CANCELED
                state.finished_at = datetime.now()
                self._cancel_requests.discard(task.task_id)
                self._state_store.upsert(state)
                logger.info(
                    "event=task_manager.task_canceled_before_start worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
                self._queue.task_done()
                continue

            state.status = DataProcessTaskStatus.RUNNING
            state.started_at = datetime.now()
            self._state_store.upsert(state)
            logger.info(
                "event=task_manager.task_started worker_id=%s task_id=%s project_id=%s",
                worker_id,
                task.task_id,
                task.project_id,
            )

            try:
                job = asyncio.create_task(self._run_data_process_task(task))
                self._running_jobs[task.task_id] = job
                await job
                state.status = DataProcessTaskStatus.COMPLETED
                state.finished_at = datetime.now()
                logger.info(
                    "event=task_manager.task_completed worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
            except asyncio.CancelledError:
                state.status = DataProcessTaskStatus.CANCELED
                state.error = "Task canceled by user"
                state.finished_at = datetime.now()
                logger.info(
                    "event=task_manager.task_canceled_running worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
            except Exception as exc:
                state.status = DataProcessTaskStatus.FAILED
                state.error = str(exc)
                state.finished_at = datetime.now()
                logger.exception(
                    "event=task_manager.task_failed worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
            finally:
                self._state_store.upsert(state)
                self._running_jobs.pop(task.task_id, None)
                self._cancel_requests.discard(task.task_id)
                if task.cleanup_path and task.cleanup_path.exists():
                    try:
                        task.cleanup_path.unlink()
                    except Exception as exc:
                        logger.warning(
                            "event=task_manager.cleanup_failed path=%s error=%s",
                            task.cleanup_path,
                            exc,
                        )
                self._queue.task_done()

    async def _run_data_process_task(self, task: DataProcessQueueTask) -> None:
        """执行单个 data-process 任务。"""
        paper_id = task.payload.get("paper_id")
        pdf_path = task.payload.get("pdf_path")

        if not isinstance(paper_id, str) or not paper_id:
            raise ValueError("Invalid paper_id in task payload")
        if not isinstance(pdf_path, str) or not pdf_path:
            raise ValueError("Invalid pdf_path in task payload")

        logger.debug(
            "event=task_manager.task_payload_loaded task_id=%s paper_id=%s pdf_path=%s",
            task.task_id,
            paper_id,
            pdf_path,
        )
        service = PaperService(get_db())
        await service.process_existing_paper(
            paper_id=paper_id,
            pdf_path=Path(pdf_path),
            max_retries=settings.DATA_PROCESS_MAX_RETRIES,
        )
