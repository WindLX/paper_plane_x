"""应用日志初始化工具。"""

from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from paper_plane_x_backend.config import settings

_active_log_file_path: Path | None = None


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


def _build_log_file_path_for_startup(base_path: Path) -> Path:
    """基于配置路径生成本次启动专属日志文件名。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = base_path.suffix if base_path.suffix else ".log"
    return base_path.with_name(f"{base_path.stem}_{timestamp}{suffix}")


def setup_logging() -> None:
    """配置全局日志（控制台 + 文件滚动输出）。"""
    global _active_log_file_path

    settings.ensure_directories()

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.log.to_file:
        _active_log_file_path = _build_log_file_path_for_startup(settings.log.file_path)
        handlers.append(
            RotatingFileHandler(
                filename=_active_log_file_path,
                maxBytes=settings.log.file_max_bytes,
                backupCount=settings.log.file_backup_count,
                encoding="utf-8",
            )
        )
    else:
        _active_log_file_path = None

    logging.basicConfig(
        level=getattr(logging, settings.log.level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=handlers,
        force=True,
    )

    if settings.log.app_only:
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


def get_active_log_file_path() -> Path | None:
    """返回本次进程启动使用的日志文件路径。"""
    return _active_log_file_path
