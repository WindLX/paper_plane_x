"""SQLite 数据库服务.

不使用 ORM，直接使用 sqlite3 模块进行数据库操作。
"""

import json
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
    title TEXT,
    authors TEXT,
    year INTEGER,
    publication TEXT,
    doi TEXT,
    custom_meta TEXT,
    md_content TEXT,
    raw_pdf_path TEXT,
    raw_pdf_sha256 TEXT,
    images_paths TEXT,
    extraction_status TEXT DEFAULT 'PENDING',
    quick_scan TEXT,
    synthesis_data TEXT,
    analysis_report TEXT,
    extraction_fact_check_status TEXT DEFAULT 'PENDING',
    extraction_fact_check_result TEXT,
    analysis_fact_check_status TEXT DEFAULT 'PENDING',
    analysis_fact_check_result TEXT,
    extraction_retry_count INTEGER DEFAULT 0,
    analysis_retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_projects (
    paper_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (paper_id, project_id),
    FOREIGN KEY (paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_traces (
    trace_id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    messages TEXT,
    llm_model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    usage_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_process_tasks (
    task_id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    error TEXT,
    retry_of_task_id TEXT,
    extraction_trace_ids TEXT,
    analysis_trace_ids TEXT,
    extraction_fact_check_trace_ids TEXT,
    analysis_fact_check_trace_ids TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    paper_id,
    title,
    md_content,
    quick_scan,
    synthesis_data,
    analysis_report,
    content='papers',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
    VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data, NEW.analysis_report);
END;

CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
    VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data, OLD.analysis_report);
END;

CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
    VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data, OLD.analysis_report);
    INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
    VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data, NEW.analysis_report);
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
            if self._needs_schema_migration(conn):
                self._backup_database_before_migration(conn)
            self._ensure_schema_migrations(conn)
            self._ensure_papers_fts_healthy(conn)
            conn.commit()
        logger.info("event=database.tables_initialized")

    def _needs_schema_migration(self, conn: sqlite3.Connection) -> bool:
        venue_exists = self._has_column(conn, "papers", "venue")
        publication_exists = self._has_column(conn, "papers", "publication")
        custom_meta_exists = self._has_column(conn, "papers", "custom_meta")
        legacy_fact_check_exists = any(
            self._has_column(conn, "papers", legacy_column)
            for legacy_column in [
                "fact_check_status",
                "fact_check_result",
                "final_fact_check_trace_id",
                "extraction_final_fact_check_trace_id",
                "analysis_final_fact_check_trace_id",
            ]
        )
        new_columns_ready = all(
            self._has_column(conn, "papers", column)
            for column in [
                "analysis_report",
                "extraction_fact_check_status",
                "extraction_fact_check_result",
                "analysis_fact_check_status",
                "analysis_fact_check_result",
                "analysis_retry_count",
            ]
        )
        task_trace_columns_ready = all(
            self._has_column(conn, "data_process_tasks", column)
            for column in [
                "extraction_trace_ids",
                "analysis_trace_ids",
                "extraction_fact_check_trace_ids",
                "analysis_fact_check_trace_ids",
            ]
        )
        agent_traces_legacy = any(
            self._has_column(conn, "agent_traces", col)
            for col in [
                "latest_input_message",
                "output_message",
                "reasoning_content",
                "message_history",
            ]
        )
        papers_trace_legacy = any(
            self._has_column(conn, "papers", col)
            for col in [
                "extraction_trace_ids",
                "extraction_fact_check_trace_ids",
                "analysis_trace_ids",
                "analysis_fact_check_trace_ids",
            ]
        )
        return (
            venue_exists
            or (not publication_exists)
            or (not custom_meta_exists)
            or legacy_fact_check_exists
            or (not new_columns_ready)
            or (not task_trace_columns_ready)
            or agent_traces_legacy
            or papers_trace_legacy
        )

    def _backup_database_before_migration(self, conn: sqlite3.Connection) -> None:
        backup_dir = self.db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.db_path.stem}_pre_migration_{timestamp}.db"

        with sqlite3.connect(backup_path) as backup_conn:
            conn.backup(backup_conn)

        logger.info("event=database.backup_created path=%s", backup_path)

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

    def _drop_papers_fts_objects(self, conn: sqlite3.Connection) -> None:
        for trigger_name in ["papers_ai", "papers_ad", "papers_au"]:
            conn.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        conn.execute("DROP TABLE IF EXISTS papers_fts")

    def _ensure_papers_fts_objects(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
                paper_id,
                title,
                md_content,
                quick_scan,
                synthesis_data,
                analysis_report,
                content='papers',
                content_rowid='rowid'
            );

            CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
                INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
                VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data, NEW.analysis_report);
            END;

            CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
                INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
                VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data, OLD.analysis_report);
            END;

            CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
                INSERT INTO papers_fts(papers_fts, rowid, paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
                VALUES ('delete', OLD.rowid, OLD.paper_id, OLD.title, OLD.md_content, OLD.quick_scan, OLD.synthesis_data, OLD.analysis_report);
                INSERT INTO papers_fts(paper_id, title, md_content, quick_scan, synthesis_data, analysis_report)
                VALUES (NEW.paper_id, NEW.title, NEW.md_content, NEW.quick_scan, NEW.synthesis_data, NEW.analysis_report);
            END;
            """
        )

    def _rebuild_papers_fts(self, conn: sqlite3.Connection) -> None:
        self._drop_papers_fts_objects(conn)
        self._ensure_papers_fts_objects(conn)
        conn.execute("INSERT INTO papers_fts(papers_fts) VALUES('rebuild')")
        logger.info("event=database.fts_rebuilt")

    @staticmethod
    def _is_fts_recoverable_error(sql: str, exc: sqlite3.DatabaseError) -> bool:
        message = str(exc).lower()
        if "fts5" in message or "papers_fts" in message:
            return True
        if "database disk image is malformed" in message and "papers" in sql.lower():
            return True
        if "malformed" in message and "virtual table" in message:
            return True
        return "corrupt" in message and "fts" in message

    def _execute_with_fts_recovery(
        self,
        conn: sqlite3.Connection,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> sqlite3.Cursor:
        try:
            return conn.execute(sql, parameters)
        except sqlite3.DatabaseError as exc:
            if not self._is_fts_recoverable_error(sql, exc):
                raise
            logger.warning(
                "event=database.fts_runtime_recovery_triggered error=%s",
                exc,
            )
            self._rebuild_papers_fts(conn)
            return conn.execute(sql, parameters)

    def _ensure_schema_migrations(self, conn: sqlite3.Connection) -> None:
        self._drop_papers_fts_objects(conn)
        venue_exists = self._has_column(conn, "papers", "venue")
        publication_exists = self._has_column(conn, "papers", "publication")
        if not publication_exists:
            self._ensure_column(conn, "papers", "publication", "TEXT")

        for fts_column in [
            "title",
            "md_content",
            "quick_scan",
            "synthesis_data",
            "analysis_report",
        ]:
            self._ensure_column(conn, "papers", fts_column, "TEXT")

        if venue_exists:
            conn.execute(
                """
                UPDATE papers
                SET publication = venue
                WHERE publication IS NULL AND venue IS NOT NULL
                """
            )
            try:
                conn.execute("ALTER TABLE papers DROP COLUMN venue")
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "event=database.drop_legacy_column_skipped table=papers column=venue error=%s",
                    exc,
                )

        self._ensure_column(conn, "papers", "custom_meta", "TEXT")
        self._ensure_column(conn, "papers", "analysis_report", "TEXT")
        self._ensure_column(
            conn,
            "papers",
            "extraction_fact_check_status",
            "TEXT DEFAULT 'PENDING'",
        )
        self._ensure_column(conn, "papers", "extraction_fact_check_result", "TEXT")
        self._ensure_column(
            conn,
            "papers",
            "analysis_fact_check_status",
            "TEXT DEFAULT 'PENDING'",
        )
        self._ensure_column(conn, "papers", "analysis_fact_check_result", "TEXT")
        self._ensure_column(conn, "papers", "analysis_retry_count", "INTEGER DEFAULT 0")
        self._migrate_legacy_fact_check_columns(conn)
        self._drop_papers_trace_columns(conn)
        self._ensure_column(conn, "papers", "raw_pdf_sha256", "TEXT")
        self._migrate_agent_traces_messages_schema(conn)
        self._ensure_column(conn, "agent_traces", "llm_model", "TEXT")
        self._ensure_column(conn, "agent_traces", "prompt_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "completion_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "total_tokens", "INTEGER")
        self._ensure_column(conn, "agent_traces", "usage_payload", "TEXT")
        self._ensure_trace_columns(conn, "data_process_tasks")
        conn.execute("DROP TABLE IF EXISTS data_process_history")
        self._ensure_papers_fts_objects(conn)

    def _ensure_trace_columns(self, conn: sqlite3.Connection, table: str) -> None:
        for column in [
            "extraction_trace_ids",
            "analysis_trace_ids",
            "extraction_fact_check_trace_ids",
            "analysis_fact_check_trace_ids",
        ]:
            self._ensure_column(conn, table, column, "TEXT")

    def _migrate_legacy_fact_check_columns(self, conn: sqlite3.Connection) -> None:
        legacy_columns = [
            "fact_check_status",
            "fact_check_result",
            "final_fact_check_trace_id",
            "extraction_final_fact_check_trace_id",
            "analysis_final_fact_check_trace_id",
        ]
        if not any(
            self._has_column(conn, "papers", column) for column in legacy_columns
        ):
            return

        if self._has_column(conn, "papers", "fact_check_status"):
            conn.execute(
                """
                UPDATE papers
                SET extraction_fact_check_status = fact_check_status
                WHERE fact_check_status IS NOT NULL
                """
            )
        if self._has_column(conn, "papers", "fact_check_result"):
            conn.execute(
                """
                UPDATE papers
                SET extraction_fact_check_result = fact_check_result
                WHERE fact_check_result IS NOT NULL
                """
            )
        for legacy_column in legacy_columns:
            if not self._has_column(conn, "papers", legacy_column):
                continue
            try:
                conn.execute(f"ALTER TABLE papers DROP COLUMN {legacy_column}")
            except sqlite3.OperationalError as exc:
                logger.warning(
                    "event=database.drop_legacy_column_skipped table=papers column=%s error=%s",
                    legacy_column,
                    exc,
                )

    def _drop_papers_trace_columns(self, conn: sqlite3.Connection) -> None:
        for column in [
            "extraction_trace_ids",
            "extraction_fact_check_trace_ids",
            "analysis_trace_ids",
            "analysis_fact_check_trace_ids",
        ]:
            if self._has_column(conn, "papers", column):
                try:
                    conn.execute(f"ALTER TABLE papers DROP COLUMN {column}")
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "event=database.drop_legacy_column_skipped table=papers column=%s error=%s",
                        column,
                        exc,
                    )

    def _migrate_agent_traces_messages_schema(self, conn: sqlite3.Connection) -> None:
        """迁移 agent_traces 旧字段到 messages 字段。

        删除 latest_input_message / output_message / reasoning_content，
        将 message_history 与 output_message 合并后写入 messages，
        最后删除 message_history。
        """
        legacy_columns = [
            "latest_input_message",
            "output_message",
            "reasoning_content",
            "message_history",
        ]
        if not any(
            self._has_column(conn, "agent_traces", col) for col in legacy_columns
        ):
            self._ensure_column(conn, "agent_traces", "messages", "TEXT")
            return

        self._ensure_column(conn, "agent_traces", "messages", "TEXT")

        has_output_message = self._has_column(conn, "agent_traces", "output_message")
        has_message_history = self._has_column(conn, "agent_traces", "message_history")

        if has_output_message or has_message_history:
            rows = conn.execute(
                "SELECT trace_id, agent_name, output_message, message_history FROM agent_traces"
            ).fetchall()
            for row in rows:
                trace_id = row["trace_id"]
                agent_name = row["agent_name"] or "UnknownAgent"
                output_msg = row["output_message"] or ""
                history_str = row["message_history"] or "[]"

                try:
                    messages: list[dict[str, Any]] = json.loads(history_str)
                    if not isinstance(messages, list):
                        messages = []
                except (json.JSONDecodeError, TypeError):
                    messages = []

                if output_msg:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": output_msg,
                            "name": agent_name,
                        }
                    )

                if messages:
                    conn.execute(
                        "UPDATE agent_traces SET messages = ? WHERE trace_id = ?",
                        (json.dumps(messages, ensure_ascii=False), trace_id),
                    )

        for col in legacy_columns:
            if self._has_column(conn, "agent_traces", col):
                try:
                    conn.execute(f"ALTER TABLE agent_traces DROP COLUMN {col}")
                except sqlite3.OperationalError as exc:
                    logger.warning(
                        "event=database.drop_legacy_column_skipped table=agent_traces column=%s error=%s",
                        col,
                        exc,
                    )

    @staticmethod
    def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(row[1] == column for row in cols)

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
            cursor = self._execute_with_fts_recovery(conn, sql, parameters)
            conn.commit()
            return cursor

    def fetchone(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> dict[str, Any] | None:
        with self.get_connection() as conn:
            cursor = self._execute_with_fts_recovery(conn, sql, parameters)
            row = cursor.fetchone()
            return dict(row) if row else None

    def fetchall(
        self,
        sql: str,
        parameters: tuple[Any, ...] | dict[str, Any] = (),
    ) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = self._execute_with_fts_recovery(conn, sql, parameters)
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
            cursor = self._execute_with_fts_recovery(conn, sql, tuple(data.values()))
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
            cursor = self._execute_with_fts_recovery(conn, sql, params)
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
            cursor = self._execute_with_fts_recovery(conn, sql, where_params)
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
