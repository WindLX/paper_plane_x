"""FastAPI 依赖注入."""

import logging
from typing import Annotated

from fastapi import Depends

from paper_plane_x_backend.services import (
    Database,
    get_db,
)
from paper_plane_x_backend.services.data_process_tasks.lifecycle import (
    get_data_process_task_manager,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)

logger = logging.getLogger(__name__)


def get_database() -> Database:
    """获取数据库实例的依赖函数.

    Returns:
        Database: 数据库实例
    """
    db = get_db()
    logger.debug("event=api.database_dependency_resolved")
    return db


def get_task_manager() -> DataProcessTaskManager:
    """获取 data-process 任务管理器单例依赖。"""
    task_manager = get_data_process_task_manager()
    logger.debug("event=api.task_manager_dependency_resolved")
    return task_manager


# 类型别名，用于路由函数参数注解
DBDep = Annotated[Database, Depends(get_database)]
TaskManagerDep = Annotated[DataProcessTaskManager, Depends(get_task_manager)]
