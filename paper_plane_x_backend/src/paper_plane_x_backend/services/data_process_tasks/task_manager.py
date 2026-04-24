"""Data Process 任务队列管理器。"""

import asyncio
import logging
from collections.abc import MutableMapping
from datetime import datetime
from pathlib import Path

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessQueueTask,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.stores import (
    DataProcessTaskStateStore,
    SQLiteDataProcessTaskStateStore,
    TaskStateStoreView,
)
from paper_plane_x_backend.services.database import get_db
from paper_plane_x_backend.services.paper.parser import PaperParser
from paper_plane_x_backend.services.paper.processor import (
    PaperProcessor,
    PaperProcessorError,
    PaperProcessResult,
)
from paper_plane_x_backend.services.paper.repository import PaperRepository

logger = logging.getLogger(__name__)


class DataProcessTaskManager:
    """管理 data-process 后台任务。"""

    def __init__(
        self,
        worker_count: int = 1,
        state_store: DataProcessTaskStateStore | None = None,
        shutdown_timeout: float = 5.0,
        task_max_seconds: float = 600.0,
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
        self._task_max_seconds = max(0.1, task_max_seconds)
        self._task_states_view = TaskStateStoreView(self._state_store)

    async def _wait_tasks_with_timeout(
        self,
        tasks: list[asyncio.Task[object]] | list[asyncio.Task[None]],
        *,
        timeout: float,
        event_name: str,
    ) -> bool:
        """等待一组任务在超时内结束。"""
        pending_tasks = [task for task in tasks if not task.done()]
        if not pending_tasks:
            return True

        try:
            await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True),
                timeout=timeout,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "event=%s timeout_seconds=%.1f pending_count=%s",
                event_name,
                timeout,
                len([task for task in pending_tasks if not task.done()]),
            )
            return False

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
                        paper_id=state.paper_id,
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

        await self._wait_tasks_with_timeout(
            running_jobs,
            timeout=self._shutdown_timeout,
            event_name="task_manager.running_jobs_cancel_timeout",
        )

        queue = self._queue
        workers = list(self._workers)

        for _ in workers:
            await queue.put(None)

        workers_stopped = await self._wait_tasks_with_timeout(
            workers,
            timeout=self._shutdown_timeout,
            event_name="task_manager.workers_stop_timeout",
        )
        if not workers_stopped:
            logger.warning(
                "event=task_manager.workers_force_stop timeout_seconds=%.1f",
                self._shutdown_timeout,
            )
            for worker in workers:
                if not worker.done():
                    worker.cancel()
            await self._wait_tasks_with_timeout(
                workers,
                timeout=self._shutdown_timeout,
                event_name="task_manager.workers_force_stop_timeout",
            )

        self._workers = []
        self._queue = None
        self._running_jobs.clear()
        self._cancel_requests.clear()
        logger.info("event=task_manager.workers_stopped")

    async def submit_task(self, task: DataProcessQueueTask) -> DataProcessTaskState:
        if self._queue is None:
            logger.error(
                "event=task_manager.submit_rejected_not_started task_id=%s paper_id=%s",
                task.task_id,
                task.paper_id,
            )
            raise RuntimeError("DataProcessTaskManager is not started")
        if self._state_store.get(task.task_id) is not None:
            logger.warning(
                "event=task_manager.submit_rejected_duplicate task_id=%s paper_id=%s",
                task.task_id,
                task.paper_id,
            )
            raise ValueError(f"Task {task.task_id} already exists")

        state = DataProcessTaskState(
            task_id=task.task_id,
            paper_id=task.paper_id,
            payload=task.payload,
            status=DataProcessTaskStatus.QUEUED,
            created_at=datetime.now(),
            retry_of_task_id=task.retry_of_task_id,
        )
        self._state_store.upsert(state)
        await self._queue.put(task)
        logger.info(
            "event=task_manager.task_submitted task_id=%s paper_id=%s",
            task.task_id,
            task.paper_id,
        )
        return state

    def list_tasks(self, *, paper_id: str | None = None) -> list[DataProcessTaskState]:
        return self._state_store.list(paper_id=paper_id)

    def get_task(self, task_id: str) -> DataProcessTaskState | None:
        return self._state_store.get(task_id)

    def cancel_task(self, task_id: str) -> DataProcessTaskState:
        state = self._state_store.get(task_id)
        if state is None:
            logger.warning("event=task_manager.cancel_not_found task_id=%s", task_id)
            raise KeyError(task_id)

        if state.status in {
            DataProcessTaskStatus.COMPLETED,
            DataProcessTaskStatus.FAILED,
            DataProcessTaskStatus.CANCELED,
        }:
            logger.warning(
                "event=task_manager.cancel_rejected_finished task_id=%s status=%s",
                task_id,
                state.status,
            )
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
                "event=task_manager.task_started worker_id=%s task_id=%s paper_id=%s",
                worker_id,
                task.task_id,
                task.paper_id,
            )

            try:
                job = asyncio.create_task(self._run_data_process_task(task))
                self._running_jobs[task.task_id] = job
                result = await asyncio.wait_for(job, timeout=self._task_max_seconds)
                self._sync_trace_ids_from_result(state, result)
                state.status = DataProcessTaskStatus.COMPLETED
                state.finished_at = datetime.now()
                logger.info(
                    "event=task_manager.task_completed worker_id=%s task_id=%s",
                    worker_id,
                    task.task_id,
                )
            except asyncio.TimeoutError:
                state.status = DataProcessTaskStatus.FAILED
                state.error = (
                    f"Task exceeded max execution time ({self._task_max_seconds:.1f}s)"
                )
                state.finished_at = datetime.now()
                logger.warning(
                    "event=task_manager.task_timeout worker_id=%s task_id=%s timeout_seconds=%.1f",
                    worker_id,
                    task.task_id,
                    self._task_max_seconds,
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
                if isinstance(exc, PaperProcessorError):
                    state.extraction_trace_ids = list(exc.extraction_trace_ids)
                    state.analysis_trace_ids = list(exc.analysis_trace_ids)
                    state.extraction_fact_check_trace_ids = list(
                        exc.extraction_fact_check_trace_ids
                    )
                    state.analysis_fact_check_trace_ids = list(
                        exc.analysis_fact_check_trace_ids
                    )
                state.status = DataProcessTaskStatus.FAILED
                state.error = str(exc)
                state.finished_at = datetime.now()
                logger.exception(
                    "event=task_manager.task_failed worker_id=%s task_id=%s paper_id=%s error=%s",
                    worker_id,
                    task.task_id,
                    task.paper_id,
                    exc,
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

    @staticmethod
    def _sync_trace_ids_from_result(
        state: DataProcessTaskState, result: PaperProcessResult | object
    ) -> None:
        state.extraction_trace_ids = list(getattr(result, "extraction_trace_ids", []))
        state.analysis_trace_ids = list(getattr(result, "analysis_trace_ids", []))
        state.extraction_fact_check_trace_ids = list(
            getattr(result, "extraction_fact_check_trace_ids", [])
        )
        state.analysis_fact_check_trace_ids = list(
            getattr(result, "analysis_fact_check_trace_ids", [])
        )

    async def _run_data_process_task(
        self, task: DataProcessQueueTask
    ) -> PaperProcessResult:
        """执行单个 data-process 任务。"""
        paper_id = task.paper_id
        pdf_path = task.payload.get("pdf_path")

        if not isinstance(pdf_path, str) or not pdf_path:
            raise ValueError("Invalid pdf_path in task payload")

        logger.debug(
            "event=task_manager.task_payload_loaded task_id=%s paper_id=%s pdf_path=%s",
            task.task_id,
            paper_id,
            pdf_path,
        )
        repo = PaperRepository(get_db())
        processor = PaperProcessor(repo=repo, parser=PaperParser())
        return await processor.process(
            paper_id=paper_id,
            pdf_path=Path(pdf_path),
            max_retries=settings.data_process.max_retries,
        )
