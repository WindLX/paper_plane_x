"""Data process worker-pool lifecycle helpers."""

import logging

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)

logger = logging.getLogger(__name__)

_task_manager_instance: DataProcessTaskManager | None = None


def get_data_process_task_manager() -> DataProcessTaskManager:
    global _task_manager_instance
    if _task_manager_instance is None:
        _task_manager_instance = DataProcessTaskManager(
            worker_count=settings.data_process.worker_count,
            shutdown_timeout=settings.data_process.shutdown_timeout,
            task_max_seconds=settings.data_process.task_max_seconds,
        )
    return _task_manager_instance


async def start_worker_pool() -> None:
    """启动 data-process worker 池。"""
    logger.info("event=task_manager.worker_pool_starting")
    await get_data_process_task_manager().start()


async def stop_worker_pool() -> None:
    """停止 data-process worker 池。"""
    logger.info("event=task_manager.worker_pool_stopping")
    await get_data_process_task_manager().stop()
