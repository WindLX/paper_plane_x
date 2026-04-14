"""Database service tests."""

from pathlib import Path

from paper_plane_x_backend.services.database import Database


def _table_columns(db: Database, table: str) -> list[str]:
    with db.get_connection() as conn:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def test_init_tables_creates_new_columns_and_drops_legacy_table(tmp_path: Path) -> None:
    """验证最新 schema 字段存在，旧表会被清理。"""
    db_path = tmp_path / "db.sqlite3"
    db = Database(db_path)

    with db.get_connection() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS data_process_history (history_id INTEGER)"
        )
        conn.commit()

    db.init_tables()

    papers_columns = _table_columns(db, "papers")
    assert "final_fact_check_trace_id" in papers_columns
    assert "raw_pdf_sha256" in papers_columns

    trace_columns = _table_columns(db, "agent_traces")
    for col in [
        "llm_model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "usage_payload",
    ]:
        assert col in trace_columns

    task_columns = _table_columns(db, "data_process_tasks")
    for col in [
        "task_id",
        "project_id",
        "payload",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "error",
        "retry_of_task_id",
    ]:
        assert col in task_columns

    with db.get_connection() as conn:
        legacy = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='data_process_history'"
        ).fetchone()
    assert legacy is None


def test_init_tables_is_idempotent(tmp_path: Path) -> None:
    """验证重复初始化不会报错。"""
    db_path = tmp_path / "db.sqlite3"
    db = Database(db_path)

    db.init_tables()
    db.init_tables()

    papers_columns = _table_columns(db, "papers")
    assert "paper_id" in papers_columns
    assert "final_fact_check_trace_id" in papers_columns
    assert "raw_pdf_sha256" in papers_columns

    task_columns = _table_columns(db, "data_process_tasks")
    assert "task_id" in task_columns
