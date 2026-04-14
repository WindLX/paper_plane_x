"""FastAPI 应用主入口."""

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from paper_plane_x_backend.api.routers import data_process, hitl, project
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services import init_database


class AppNamespaceFilter(logging.Filter):
    """仅放行应用命名空间日志。"""

    def __init__(self, namespace_prefixes: tuple[str, ...]) -> None:
        super().__init__()
        self.namespace_prefixes = namespace_prefixes

    def filter(self, record: logging.LogRecord) -> bool:
        return any(
            record.name == prefix or record.name.startswith(f"{prefix}.")
            for prefix in self.namespace_prefixes
        )


def setup_logging() -> None:
    """配置全局日志（控制台 + 文件滚动输出）。"""
    settings.ensure_directories()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.LOG_TO_FILE:
        handlers.append(
            RotatingFileHandler(
                filename=settings.LOG_FILE_PATH,
                maxBytes=settings.LOG_FILE_MAX_BYTES,
                backupCount=settings.LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )

    if settings.LOG_APP_ONLY:
        app_filter = AppNamespaceFilter(("paper_plane_x_backend",))
        for handler in logging.getLogger().handlers:
            handler.addFilter(app_filter)

        # 第三方库日志统一抬高阈值，避免刷屏。
        for logger_name in (
            "uvicorn",
            "uvicorn.error",
            "uvicorn.access",
            "fastapi",
            "watchfiles",
            "httpx",
            "litellm",
            "LiteLLM",
            "asyncio",
        ):
            logging.getLogger(logger_name).setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title=settings.APP_NAME,
    description="AI Agent-powered research survey data-process system",
    version="0.1.0",
    debug=settings.DEBUG,
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
app.include_router(data_process.router, prefix="/api/v1")
app.include_router(hitl.router, prefix="/api/v1")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动事件（Lifespan）."""
    settings.ensure_directories()
    init_database()
    await data_process.start_worker_pool()
    logger.info(
        "event=app.startup_completed log_file=%s",
        str(settings.LOG_FILE_PATH) if settings.LOG_TO_FILE else "disabled",
    )
    yield
    await data_process.stop_worker_pool()
    logger.info("event=app.shutdown_completed")


app.router.lifespan_context = lifespan


@app.get("/health")
async def health_check():
    """健康检查接口."""
    return {"status": "ok", "app_name": settings.APP_NAME}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
