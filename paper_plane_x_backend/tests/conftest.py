"""Pytest 配置和 fixtures."""

import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from paper_plane_x_backend.api.dependencies import get_database
from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services import Database, init_database

# 在导入 app 之前切换测试运行目录，避免生命周期初始化写入 ./data。
_TEST_RUNTIME_DIR = Path(tempfile.mkdtemp(prefix="ppx-tests-"))
settings.DATA_DIR = _TEST_RUNTIME_DIR
settings.MINERU_OUTPUT_DIR = _TEST_RUNTIME_DIR / "papers"
settings.LOG_FILE_PATH = _TEST_RUNTIME_DIR / "logs" / "backend.log"


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_runtime_dir() -> Generator[None, None, None]:
    """会话结束后清理测试运行目录."""
    yield
    shutil.rmtree(_TEST_RUNTIME_DIR, ignore_errors=True)


@pytest.fixture
def temp_db_path() -> Generator[Path, None, None]:
    """创建临时数据库文件路径."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    # 清理
    path.unlink(missing_ok=True)


@pytest.fixture
def db(temp_db_path: Path) -> Generator[Database, None, None]:
    """创建并初始化测试数据库."""
    database = init_database(temp_db_path)
    yield database


@pytest.fixture
def client(db: Database) -> Generator[TestClient, None, None]:
    """创建测试客户端，使用测试数据库."""
    from paper_plane_x_backend.main import app

    # 覆盖依赖注入，使用测试数据库
    def override_get_db() -> Database:
        return db

    app.dependency_overrides[get_database] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    # 清理依赖覆盖
    app.dependency_overrides.clear()
