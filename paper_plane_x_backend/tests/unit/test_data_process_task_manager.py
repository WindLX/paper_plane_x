"""DataProcessTaskManager tests."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from paper_plane_x_backend.models import DataProcessTaskStatus
from paper_plane_x_backend.services.data_process_task_manager import (
    DataProcessQueueTask,
    DataProcessTaskManager,
    DataProcessTaskState,
    InMemoryDataProcessTaskStateStore,
    SQLiteDataProcessTaskStateStore,
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
            project_id="project-1",
            payload={"paper_id": "paper-1", "pdf_path": "/tmp/fake.pdf"},
        )
    )

    await asyncio.wait_for(started.wait(), timeout=1.0)
    await asyncio.wait_for(manager.stop(), timeout=1.0)

    updated = manager.get_task(task_state.task_id)
    assert updated is not None
    assert updated.status == DataProcessTaskStatus.CANCELED


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
            project_id="project-1",
            payload={"paper_id": "paper-1", "pdf_path": "/tmp/fake.pdf"},
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
            project_id="project-1",
            payload={"paper_id": "paper-1", "pdf_path": "/tmp/fake.pdf"},
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
async def test_cancel_already_canceled_task_raises_value_error() -> None:
    """验证重复取消已结束任务会报冲突。"""
    manager = _new_in_memory_manager()

    await manager.start()
    task_state = await manager.submit_task(
        DataProcessQueueTask(
            task_id="task-repeat-cancel",
            project_id="project-1",
            payload={"paper_id": "paper-1", "pdf_path": "/tmp/fake.pdf"},
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
        project_id="project-1",
        payload={"paper_id": "paper-1", "pdf_path": "/tmp/fake.pdf"},
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
