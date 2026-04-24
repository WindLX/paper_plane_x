"""DataProcessTaskManager tests."""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services.data_process_tasks.models import (
    DataProcessQueueTask,
    DataProcessTaskState,
)
from paper_plane_x_backend.services.data_process_tasks.stores import (
    InMemoryDataProcessTaskStateStore,
    SQLiteDataProcessTaskStateStore,
)
from paper_plane_x_backend.services.data_process_tasks.task_manager import (
    DataProcessTaskManager,
)


def _new_in_memory_manager() -> DataProcessTaskManager:
    return DataProcessTaskManager(
        worker_count=1,
        state_store=InMemoryDataProcessTaskStateStore(),
        shutdown_timeout=0.2,
    )


@pytest.mark.asyncio
async def test_stop_cancels_running_job_quickly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 stop 会取消运行中任务，避免关闭阻塞。"""
    manager = _new_in_memory_manager()
    started = asyncio.Event()

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()
    task_state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-1",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )

    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.wait_for(manager.stop(), timeout=1.0)

    updated = manager.get_task(task_state.task_id)
    assert updated is not None
    assert updated.status == DataProcessTaskStatus.CANCELED


@pytest.mark.asyncio
async def test_stop_returns_when_running_job_cancels_slowly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证运行任务取消较慢时 stop 仍会在超时后返回。"""
    manager = DataProcessTaskManager(
        worker_count=1,
        state_store=InMemoryDataProcessTaskStateStore(),
        shutdown_timeout=0.1,
    )
    started = asyncio.Event()

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.sleep(0.5)
            raise

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()
    await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-slow-cancel",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )

    await asyncio.wait_for(started.wait(), timeout=1.0)
    begin = time.monotonic()
    await manager.stop()
    elapsed = time.monotonic() - begin

    assert elapsed < 0.6


@pytest.mark.asyncio
async def test_task_fails_when_exceeding_max_execution_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证任务执行超过上限时会被标记为 FAILED。"""
    manager = DataProcessTaskManager(
        worker_count=1,
        state_store=InMemoryDataProcessTaskStateStore(),
        shutdown_timeout=0.2,
        task_max_seconds=0.05,
    )

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.2)

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()
    state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-timeout",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )

    for _ in range(40):
        latest = manager.get_task(state.task_id)
        if latest and latest.status == DataProcessTaskStatus.FAILED:
            break
        await asyncio.sleep(0.01)

    latest = manager.get_task(state.task_id)
    assert latest is not None
    assert latest.status == DataProcessTaskStatus.FAILED
    assert latest.error is not None
    assert "exceeded max execution time" in latest.error

    await manager.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    """验证 stop 可重复调用。"""
    manager = _new_in_memory_manager()

    await manager.start()
    await manager.stop()
    await manager.stop()


@pytest.mark.asyncio
async def test_cancel_running_task_transitions_to_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证运行中任务取消后最终状态为 CANCELED。"""
    manager = _new_in_memory_manager()
    started = asyncio.Event()

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()
    task_state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-running",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    canceled = manager.cancel_task(task_state.task_id)
    assert canceled.status == DataProcessTaskStatus.CANCELING

    for _ in range(20):
        latest = manager.get_task(task_state.task_id)
        if latest and latest.status == DataProcessTaskStatus.CANCELED:
            break
        await asyncio.sleep(0.01)

    latest = manager.get_task(task_state.task_id)
    assert latest is not None
    assert latest.status == DataProcessTaskStatus.CANCELED

    await manager.stop()


@pytest.mark.asyncio
async def test_cleanup_path_is_removed_after_task_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证任务结束后 cleanup_path 会被清理。"""
    manager = _new_in_memory_manager()

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    cleanup = tmp_path / "to_cleanup.pdf"
    cleanup.write_bytes(b"dummy")

    await manager.start()
    state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-clean",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
            cleanup_path=cleanup,
        )
    )

    for _ in range(20):
        latest = manager.get_task(state.task_id)
        if latest and latest.status == DataProcessTaskStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)

    assert not cleanup.exists()
    await manager.stop()


@pytest.mark.asyncio
async def test_completed_task_copies_trace_ids_from_processor_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _new_in_memory_manager()

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            extraction_trace_ids=["trace-extraction"],
            analysis_trace_ids=["trace-analysis"],
            extraction_fact_check_trace_ids=["trace-extraction-fc"],
            analysis_fact_check_trace_ids=["trace-analysis-fc"],
        )

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()
    state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-result-traces",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )

    for _ in range(20):
        latest = manager.get_task(state.task_id)
        if latest and latest.status == DataProcessTaskStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)

    latest = manager.get_task(state.task_id)
    assert latest is not None
    assert latest.extraction_trace_ids == ["trace-extraction"]
    assert latest.analysis_trace_ids == ["trace-analysis"]
    assert latest.extraction_fact_check_trace_ids == ["trace-extraction-fc"]
    assert latest.analysis_fact_check_trace_ids == ["trace-analysis-fc"]

    await manager.stop()


@pytest.mark.asyncio
async def test_cancel_already_canceled_task_raises_value_error() -> None:
    """验证重复取消已结束任务会报冲突。"""
    manager = _new_in_memory_manager()

    await manager.start()
    task_state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-repeat-cancel",
            paper_id="paper-1",
            payload={"pdf_path": "/tmp/fake.pdf"},
        )
    )

    first = manager.cancel_task(task_state.task_id)
    assert first.status == DataProcessTaskStatus.CANCELED

    with pytest.raises(ValueError):
        manager.cancel_task(task_state.task_id)

    await manager.stop()


@pytest.mark.asyncio
async def test_start_recovers_queued_tasks_from_database(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证服务重启后可从数据库恢复排队任务。"""
    state_store = SQLiteDataProcessTaskStateStore(db)
    queued_state = DataProcessTaskState(
        task_id="task-recover-1",
        paper_id="paper-1",
        payload={"pdf_path": "/tmp/fake.pdf"},
        status=DataProcessTaskStatus.QUEUED,
        created_at=datetime.now(),
    )
    state_store.upsert(queued_state)

    manager = DataProcessTaskManager(
        worker_count=1,
        state_store=state_store,
        shutdown_timeout=0.2,
    )

    async def fake_run(self, task):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(DataProcessTaskManager, "_run_data_process_task", fake_run)

    await manager.start()

    for _ in range(40):
        latest = manager.get_task("task-recover-1")
        if latest and latest.status == DataProcessTaskStatus.COMPLETED:
            break
        await asyncio.sleep(0.01)

    latest = manager.get_task("task-recover-1")
    assert latest is not None
    assert latest.status == DataProcessTaskStatus.COMPLETED

    await manager.stop()


def test_sqlite_task_state_store_round_trips_trace_ids(db) -> None:
    store = SQLiteDataProcessTaskStateStore(db)
    state = DataProcessTaskState(
        task_id="task-traces",
        paper_id="paper-traces",
        payload={"pdf_path": "/tmp/fake.pdf"},
        status=DataProcessTaskStatus.COMPLETED,
        created_at=datetime.now(),
        extraction_trace_ids=["trace-extraction"],
        analysis_trace_ids=["trace-analysis"],
        extraction_fact_check_trace_ids=["trace-extraction-fc"],
        analysis_fact_check_trace_ids=["trace-analysis-fc"],
    )

    store.upsert(state)

    loaded = store.get("task-traces")
    assert loaded is not None
    assert loaded.extraction_trace_ids == ["trace-extraction"]
    assert loaded.analysis_trace_ids == ["trace-analysis"]
    assert loaded.extraction_fact_check_trace_ids == ["trace-extraction-fc"]
    assert loaded.analysis_fact_check_trace_ids == ["trace-analysis-fc"]
