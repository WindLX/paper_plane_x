"""FastAPI 应用主入口."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paper_plane_x_backend.api.routers import (
    data_process,
    hitl,
    librarian,
    paper,
    project,
)
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services import init_database
from paper_plane_x_backend.services.data_process_tasks.lifecycle import (
    start_worker_pool,
    stop_worker_pool,
)
from paper_plane_x_backend.utils.logging import (
    get_active_log_file_path,
    setup_logging,
)

setup_logging()
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.app_name,
    description="AI Agent-powered research survey data-process system",
    version="0.1.0",
    debug=settings.debug,
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应配置具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(project.router, prefix="/api/v1")
app.include_router(paper.router, prefix="/api/v1")
app.include_router(librarian.router, prefix="/api/v1")
app.include_router(data_process.router, prefix="/api/v1")
app.include_router(hitl.router, prefix="/api/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动事件（Lifespan）."""
    settings.ensure_directories()
    init_database()
    await start_worker_pool()
    logger.info(
        "event=app.startup_completed log_file=%s",
        (
            str(get_active_log_file_path())
            if get_active_log_file_path() is not None
            else "disabled"
        ),
    )
    yield
    await stop_worker_pool()
    logger.info("event=app.shutdown_completed")


app.router.lifespan_context = lifespan


@app.get("/health")
async def health_check():
    """健康检查接口."""
    return {"status": "ok", "app_name": settings.app_name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
