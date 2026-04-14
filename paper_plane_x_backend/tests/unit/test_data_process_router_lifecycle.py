"""Data-process router lifecycle tests."""

import pytest

from paper_plane_x_backend.api.routers import data_process


class _FakeManager:
    def __init__(self) -> None:
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_start_stop_worker_pool_delegate_to_task_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeManager()
    monkeypatch.setattr(data_process, "_task_manager", fake)

    await data_process.start_worker_pool()
    await data_process.stop_worker_pool()

    assert fake.start_calls == 1
    assert fake.stop_calls == 1
