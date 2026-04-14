"""SQLite 数据库服务.

不使用 ORM，直接使用 sqlite3 模块进行数据库操作。
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from paper_plane_x_backend.config import settings

logger = logging.getLogger(__name__)


def _adapt_datetime(value: datetime) -> str:
    return value.isoformat(sep=" ")


def _convert_timestamp(value: bytes) -> datetime:
    return datetime.fromisoformat(value.decode("utf-8"))


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("timestamp", _convert_timestamp)
sqlite3.register_converter("datetime", _convert_timestamp)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    operation_logs TEXT
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT,
    authors TEXT,
    year INTEGER,
    venue TEXT,
    doi TEXT,
    md_content TEXT,
    raw_pdf_path TEXT,
    raw_pdf_sha256 TEXT,
    images_paths TEXT,
    extraction_status TEXT DEFAULT 'PENDING',
    quick_scan TEXT,
    synthesis_data TEXT,
    fact_check_status TEXT DEFAULT 'PENDING',
    fact_check_result TEXT,
    final_fact_check_trace_id TEXT,
    extraction_retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_traces (
    trace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    latest_input_message TEXT,
    output_message TEXT,
    message_history TEXT,
    llm_model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    usage_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS data_process_tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error TEXT,
    retry_of_task_id TEXT,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id,
    title,
    md_content,
    quick_scan,
    synthesis_data,
    content='papers',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data)
    VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data);
END;

CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data)
    VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data);
END;

CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data)
    VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data);
    INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data)
    VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data);
END;
"""


class Database:
    """数据库操作类。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else settings.database_path
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_tables(self) -> None:
        with self.get_connection() as conn:
            self._configure_connection_pragmas(conn)
            conn.executescript(CREATE_TABLES_SQL)
            self._ensure_schema_migrations(conn)
            self._ensure_papers_fts_healthy(conn)
            conn.commit()
        logger.info("event=database.tables_initialized")

    @staticmethod
    def _configure_connection_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")

    def _ensure_papers_fts_healthy(self, conn: sqlite3.Connection) -> None:
        """确保 papers_fts 可用且与 papers 表同步。"""
        try:
            # FTS5 integrity-check 会在索引损坏时抛 DatabaseError。
            conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('integrity-check')")
        except sqlite3.DatabaseError as exc:
            if "malformed" in str(exc).lower():
                logger.warning("event=database.fts_corruption_detected error=%s", exc)
                self._rebuild_papers_fts(conn)
            else:
                raise

        row = conn.execute(
            "SELECT (SELECT COUNT(*) FROM papers) AS papers_count, "
            "(SELECT COUNT(*) FROM papers_fts) AS fts_count"
        ).fetchone()
        papers_count = int(row[0]) if row else 0
        fts_count = int(row[1]) if row else 0
        if papers_count != fts_count:
            logger.warning(
                "event=database.fts_count_mismatch papers_count=%s fts_count=%s",
                papers_count,
                fts_count,
            )
            conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")

    def _rebuild_papers_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP TABLE IF EXISTS papers_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE papers_fts USING fts5("
            "paper_id, title, md_content, quick_scan, synthesis_data, "
            "content='papers', content_rowid='rowid')"
        )
        conn.execute(
            "INSERT INTO papers_fts(rowid, paper_id, title, md_content, quick_scan, synthesis_data) "
            "SELECT rowid, paper_id, title, md_content, quick_scan, synthesis_data FROM papers"
        )
        logger.info("event=database.fts_rebuilt")

    def _ensure_schema_migrations(self, conn: sqlite3.Connection) -> None:
        self._ensure_column(conn, "papers", "final_fact_check_trace_id", "TEXT")
        self._ensure_column(conn, "papers", "raw_pdf_sha256", "TEXT")
        self._ensure_column(conn, "agent_traces", "llm_model", "TEXT")
        self._ensure_column(conn, "agent_traces", "prompt_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "completion_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "total_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "usage_payload", "TEXT")
        conn.execute("DROP TABLE IF EXISTS data_process_history")

    @staticmethod
    def _ensure_column(
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_cols = {row[1] for row in cols}
        if column not in existing_cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def execute(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> sqlite3.Cursor:
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            conn.commit()
            return cursor

    def fetchone(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetchall(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.execute(sql, parameters)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def insert(
        self,
        table: str,
        data: dict[str, Any],
    ) -> int | None:
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, tuple(data.values()))
            conn.commit()
            return cursor.lastrowid

    def update(
        self,
        table: str,
        data: dict[str, Any],
        where: str,
        where_params: tuple[Any, ...],
    ) -> int:
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        params = tuple(data.values()) + where_params

        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    def delete(
        self,
        table: str,
        where: str,
        where_params: tuple[Any, ...],
    ) -> int:
        sql = f"DELETE FROM {table} WHERE {where}"

        with self.get_connection() as conn:
            cursor = conn.execute(sql, where_params)
            conn.commit()
            return cursor.rowcount

    def search_fulltext(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT p.*, rank
            FROM papers_fts
            JOIN papers p ON papers_fts.paper_id = p.paper_id
            WHERE papers_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        return self.fetchall(sql, (query, limit))


def init_database(db_path: Path | str | None = None) -> Database:
    db = Database(db_path)
    db.init_tables()
    return db


_db_instance: Database | None = None


def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
