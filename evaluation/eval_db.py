# evaluation/eval_db.py
from __future__ import annotations
# Database connection and schema for the AI eval pipeline.
#
# Dual-mode: uses PostgreSQL when DATABASE_URL is set, falls back to SQLite
# for local dev and smoke tests that pass an explicit db_path.
#
# Five tables:
#   prompts           — versioned prompt registry
#   eval_runs         — one row per full pipeline run against a golden-set entry
#   token_usage       — one row per LLM call, linked to an eval run
#   audit_trail       — ordered decision trace for one pipeline run
#   prompt_promotions — promotion decisions for prompt versions

import os
import sqlite3
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras

DEFAULT_DB_PATH = Path(__file__).parent / "eval.db"


# ---------------------------------------------------------------------------
# PostgreSQL connection wrapper
# ---------------------------------------------------------------------------

class _PgConn:
    """Wraps a psycopg2 connection with a sqlite3-compatible interface.

    Exposes execute(), executemany(), commit(), rollback(), close(), and
    the context manager protocol so existing ``with conn:`` call sites work
    unchanged across both backends.
    """

    def __init__(self, raw_conn) -> None:
        self._conn = raw_conn
        self._cur = raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql: str, params=None):
        self._cur.execute(sql, params)
        return self._cur

    def executemany(self, sql: str, seq):
        self._cur.executemany(sql, seq)
        return self._cur

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._cur.close()
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_connection(db_path: Path | None = None):
    """Return a DB connection.

    Uses PostgreSQL when DATABASE_URL is set and db_path is None.
    Falls back to SQLite for local dev and tests that supply an explicit path.
    """
    if DATABASE_URL and db_path is None:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return _PgConn(conn)
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def is_postgres(db_path=None) -> bool:
    """True when the connection for db_path would use PostgreSQL.

    Mirrors get_connection() logic exactly: PostgreSQL only when DATABASE_URL
    is set AND db_path is None (i.e. no explicit SQLite path override).
    """
    return bool(DATABASE_URL) and db_path is None


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they don't already exist."""
    conn = get_connection(db_path)
    try:
        if is_postgres() and db_path is None:
            _init_postgres(conn)
        else:
            _init_sqlite(conn)
        _migrate_columns(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initializers
# ---------------------------------------------------------------------------

def _init_postgres(conn) -> None:
    """Create all tables in PostgreSQL (idempotent)."""
    statements = [
        """CREATE TABLE IF NOT EXISTS prompts (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            version       INTEGER NOT NULL,
            agent         TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            created_at    TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS eval_runs (
            id             TEXT PRIMARY KEY,
            golden_set_id  TEXT    NOT NULL,
            feature_type   TEXT    NOT NULL,
            prompt_id      TEXT    REFERENCES prompts(id),
            run_at         TIMESTAMP DEFAULT NOW(),
            original_score INTEGER,
            final_score    INTEGER,
            passed         INTEGER,
            scorecard      TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS token_usage (
            id            SERIAL PRIMARY KEY,
            run_id        TEXT    NOT NULL REFERENCES eval_runs(id),
            agent         TEXT    NOT NULL,
            model         TEXT    NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            call_at       TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_golden ON eval_runs(golden_set_id, run_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_token_usage_run ON token_usage(run_id)",
        """CREATE TABLE IF NOT EXISTS audit_trail (
            id           SERIAL PRIMARY KEY,
            run_id       TEXT    NOT NULL REFERENCES eval_runs(id),
            event_type   TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL,
            details_json TEXT    NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_audit_trail_run ON audit_trail(run_id, timestamp)",
        """CREATE TABLE IF NOT EXISTS prompt_promotions (
            id            SERIAL PRIMARY KEY,
            prompt_name   TEXT    NOT NULL,
            from_version  INTEGER,
            to_version    INTEGER NOT NULL,
            decision      TEXT    NOT NULL,
            reasons_json  TEXT    NOT NULL,
            decided_at    TIMESTAMP DEFAULT NOW()
        )""",
        "CREATE INDEX IF NOT EXISTS idx_prompt_promotions_name ON prompt_promotions(prompt_name, decided_at DESC)",
        """CREATE TABLE IF NOT EXISTS feature_requests (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            description   TEXT NOT NULL,
            notes         TEXT DEFAULT '',
            feature_type  TEXT,
            status        TEXT NOT NULL DEFAULT 'draft',
            boost_inputs  TEXT DEFAULT '{}',
            generated_spec TEXT,
            score         INTEGER,
            run_cost      REAL,
            run_id        TEXT,
            created_at    TIMESTAMP DEFAULT NOW(),
            completed_at  TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_feature_requests_status ON feature_requests(status)",
    ]
    for sql in statements:
        conn.execute(sql)
    conn.commit()


def _init_sqlite(conn) -> None:
    """Create all tables in SQLite (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prompts (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            version       INTEGER NOT NULL,
            agent         TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS eval_runs (
            id             TEXT PRIMARY KEY,
            golden_set_id  TEXT    NOT NULL,
            feature_type   TEXT    NOT NULL,
            prompt_id      TEXT    REFERENCES prompts(id),
            run_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            original_score INTEGER,
            final_score    INTEGER,
            passed         INTEGER,
            scorecard      TEXT
        );

        CREATE TABLE IF NOT EXISTS token_usage (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id        TEXT    NOT NULL REFERENCES eval_runs(id),
            agent         TEXT    NOT NULL,
            model         TEXT    NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            call_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_eval_runs_golden
            ON eval_runs(golden_set_id, run_at DESC);

        CREATE INDEX IF NOT EXISTS idx_token_usage_run
            ON token_usage(run_id);

        CREATE TABLE IF NOT EXISTS audit_trail (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT    NOT NULL REFERENCES eval_runs(id),
            event_type   TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL,
            details_json TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_trail_run
            ON audit_trail(run_id, timestamp);

        CREATE TABLE IF NOT EXISTS prompt_promotions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_name   TEXT    NOT NULL,
            from_version  INTEGER,
            to_version    INTEGER NOT NULL,
            decision      TEXT    NOT NULL,
            reasons_json  TEXT    NOT NULL,
            decided_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_prompt_promotions_name
            ON prompt_promotions(prompt_name, decided_at DESC);

        CREATE TABLE IF NOT EXISTS feature_requests (
            id             TEXT PRIMARY KEY,
            title          TEXT NOT NULL,
            description    TEXT NOT NULL,
            notes          TEXT DEFAULT '',
            feature_type   TEXT,
            status         TEXT NOT NULL DEFAULT 'draft',
            boost_inputs   TEXT DEFAULT '{}',
            generated_spec TEXT,
            score          INTEGER,
            run_cost       REAL,
            run_id         TEXT,
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at   TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_feature_requests_status
            ON feature_requests(status);
    """)


# ---------------------------------------------------------------------------
# Column migrations (idempotent)
# ---------------------------------------------------------------------------

def _migrate_columns(conn) -> None:
    """Add columns introduced after the initial schema — idempotent."""
    if isinstance(conn, _PgConn):
        conn.execute("ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS router_prompt_id TEXT")
        conn.execute("ALTER TABLE eval_runs ADD COLUMN IF NOT EXISTS classified_as TEXT")
        conn.commit()
    else:
        migrations = [
            ("eval_runs", "router_prompt_id", "TEXT"),
            ("eval_runs", "classified_as",    "TEXT"),
        ]
        for table, column, col_type in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists
