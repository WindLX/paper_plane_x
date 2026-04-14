"""FastAPI 依赖注入."""

import logging
from typing import Annotated

from fastapi import Depends

from paper_plane_x_backend.services import Database, get_db

logger = logging.getLogger(__name__)


def get_database() -> Database:
    """获取数据库实例的依赖函数.

    Returns:
        Database: 数据库实例
    """
    db = get_db()
    logger.debug("event=api.database_dependency_resolved")
    return db


# 类型别名，用于路由函数参数注解
DBDep = Annotated[Database, Depends(get_database)]
