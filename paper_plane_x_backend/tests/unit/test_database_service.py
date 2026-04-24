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
    assert "extraction_trace_ids" not in papers_columns
    assert "analysis_trace_ids" not in papers_columns
    assert "extraction_fact_check_trace_ids" not in papers_columns
    assert "analysis_fact_check_trace_ids" not in papers_columns
    assert "extraction_final_fact_check_trace_id" not in papers_columns
    assert "analysis_final_fact_check_trace_id" not in papers_columns
    assert "raw_pdf_sha256" in papers_columns

    trace_columns = _table_columns(db, "agent_traces")
    for col in [
        "messages",
        "llm_model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "usage_payload",
    ]:
        assert col in trace_columns
    assert "latest_input_message" not in trace_columns
    assert "output_message" not in trace_columns
    assert "reasoning_content" not in trace_columns
    assert "message_history" not in trace_columns

    task_columns = _table_columns(db, "data_process_tasks")
    for col in [
        "task_id",
        "paper_id",
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
    assert "extraction_trace_ids" not in papers_columns
    assert "analysis_trace_ids" not in papers_columns
    assert "extraction_fact_check_trace_ids" not in papers_columns
    assert "analysis_fact_check_trace_ids" not in papers_columns
    assert "extraction_final_fact_check_trace_id" not in papers_columns
    assert "analysis_final_fact_check_trace_id" not in papers_columns
    assert "raw_pdf_sha256" in papers_columns

    task_columns = _table_columns(db, "data_process_tasks")
    assert "task_id" in task_columns
    assert "extraction_trace_ids" in task_columns


def test_migration_drops_legacy_trace_columns_and_migrates_status(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    db = Database(db_path)

    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE papers (
                paper_id TEXT PRIMARY KEY,
                title TEXT,
                authors TEXT,
                publication TEXT,
                md_content TEXT,
                images_paths TEXT,
                extraction_status TEXT,
                fact_check_status TEXT,
                fact_check_result TEXT,
                final_fact_check_trace_id TEXT,
                extraction_final_fact_check_trace_id TEXT,
                analysis_final_fact_check_trace_id TEXT,
                extraction_trace_ids TEXT,
                extraction_fact_check_trace_ids TEXT,
                analysis_trace_ids TEXT,
                analysis_fact_check_trace_ids TEXT,
                extraction_retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO papers (
                paper_id, extraction_status, fact_check_status,
                fact_check_result, final_fact_check_trace_id,
                extraction_trace_ids, extraction_fact_check_trace_ids,
                analysis_trace_ids, analysis_fact_check_trace_ids,
                created_at, updated_at
            )
            VALUES (
                'p1', 'COMPLETED', 'PASSED', 'all good',
                'trace-legacy-extraction',
                '["trace-extraction-1"]',
                '["trace-fc-1"]',
                '["trace-analysis-1"]',
                '["trace-analysis-fc-1"]',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

    db.init_tables()

    row = db.fetchone(
        """
        SELECT extraction_fact_check_status, extraction_fact_check_result
        FROM papers WHERE paper_id = ?
        """,
        ("p1",),
    )
    assert row is not None
    assert row["extraction_fact_check_status"] == "PASSED"
    assert row["extraction_fact_check_result"] == "all good"

    papers_columns = _table_columns(db, "papers")
    assert "final_fact_check_trace_id" not in papers_columns
    assert "extraction_final_fact_check_trace_id" not in papers_columns
    assert "analysis_final_fact_check_trace_id" not in papers_columns
    assert "extraction_trace_ids" not in papers_columns
    assert "extraction_fact_check_trace_ids" not in papers_columns
    assert "analysis_trace_ids" not in papers_columns
    assert "analysis_fact_check_trace_ids" not in papers_columns


def test_update_auto_recovers_from_fts_corruption(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite3"
    db = Database(db_path)
    db.init_tables()

    db.insert(
        "papers",
        {
            "paper_id": "p1",
            "title": "origin",
            "md_content": "content",
        },
    )

    # 模拟 FTS shadow table 损坏，触发运行时恢复路径。
    with db.get_connection() as conn:
        conn.execute("DROP TABLE papers_fts_data")
        conn.commit()

    affected = db.update(
        "papers",
        {"title": "updated"},
        "paper_id = ?",
        ("p1",),
    )
    assert affected == 1

    row = db.fetchone("SELECT title FROM papers WHERE paper_id = ?", ("p1",))
    assert row is not None
    assert row["title"] == "updated"

    with db.get_connection() as conn:
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('integrity-check')")


def test_migration_merges_agent_traces_output_into_messages(tmp_path: Path) -> None:
    """验证 agent_traces 的旧字段合并迁移。"""
    import json

    db_path = tmp_path / "legacy_agent_traces.sqlite3"
    db = Database(db_path)

    with db.get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE agent_traces (
                trace_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                latest_input_message TEXT,
                output_message TEXT,
                reasoning_content TEXT,
                message_history TEXT,
                llm_model TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                total_tokens INTEGER,
                usage_payload TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        history = json.dumps(
            [
                {"role": "system", "content": "You are a bot"},
                {"role": "user", "content": "hello"},
            ],
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT INTO agent_traces (
                trace_id, agent_name, latest_input_message, output_message,
                reasoning_content, message_history, llm_model
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t1",
                "ExtractionAgent",
                '{"input": "data"}',
                '{"result": "ok"}',
                "thinking...",
                history,
                "gpt-4",
            ),
        )
        conn.commit()

    db.init_tables()

    trace_columns = _table_columns(db, "agent_traces")
    assert "messages" in trace_columns
    assert "latest_input_message" not in trace_columns
    assert "output_message" not in trace_columns
    assert "reasoning_content" not in trace_columns
    assert "message_history" not in trace_columns

    row = db.fetchone("SELECT messages FROM agent_traces WHERE trace_id = ?", ("t1",))
    assert row is not None
    messages = json.loads(row["messages"])
    assert len(messages) == 3
    assert messages[0] == {"role": "system", "content": "You are a bot"}
    assert messages[1] == {"role": "user", "content": "hello"}
    assert messages[2] == {
        "role": "assistant",
        "content": '{"result": "ok"}',
        "name": "ExtractionAgent",
    }
