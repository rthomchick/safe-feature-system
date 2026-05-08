# evaluation/eval_db.py
from __future__ import annotations
# SQLite schema for the AI eval pipeline.
#
# Three tables:
#   prompts      — versioned prompt registry
#   eval_runs    — one row per full pipeline run against a golden-set entry
#   token_usage  — one row per LLM call, linked to an eval run

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent / "eval.db"


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create all tables if they don't already exist."""
    with get_connection(db_path) as conn:
        conn.executescript("""
        -- Versioned prompt registry.
        -- id is a 16-char SHA-256 prefix of the system_prompt text, so identical
        -- content always maps to the same id (content-addressed, idempotent).
        CREATE TABLE IF NOT EXISTS prompts (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            version       INTEGER NOT NULL,
            agent         TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- One row per complete pipeline run against a golden-set entry.
        -- scorecard stores the reviewer JSON blob verbatim.
        CREATE TABLE IF NOT EXISTS eval_runs (
            id             TEXT PRIMARY KEY,
            golden_set_id  TEXT    NOT NULL,
            feature_type   TEXT    NOT NULL,
            prompt_id      TEXT    REFERENCES prompts(id),
            run_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            original_score INTEGER,
            final_score    INTEGER,
            passed         INTEGER,   -- 1 = True, 0 = False, NULL = not evaluated
            scorecard      TEXT       -- JSON blob from reviewer
        );

        -- One row per LLM call within a run.
        -- agent identifies which pipeline stage made the call (router, generator, etc.).
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

        -- Ordered decision trace for one pipeline run.
        -- event_type is one of the constants defined in audit_trail.py.
        -- details_json stores the event-specific payload verbatim.
        CREATE TABLE IF NOT EXISTS audit_trail (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT    NOT NULL REFERENCES eval_runs(id),
            event_type   TEXT    NOT NULL,
            timestamp    TEXT    NOT NULL,   -- ISO-8601, e.g. 2026-04-10T14:30:00
            details_json TEXT    NOT NULL    -- JSON blob
        );

        CREATE INDEX IF NOT EXISTS idx_audit_trail_run
            ON audit_trail(run_id, timestamp);

        -- Prompt promotion decisions.
        -- Records every can_promote_prompt() call that was acted on via
        -- record_promotion(), whether approved or rejected.
        CREATE TABLE IF NOT EXISTS prompt_promotions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_name   TEXT    NOT NULL,
            from_version  INTEGER,          -- NULL when promoting to first production version
            to_version    INTEGER NOT NULL,
            decision      TEXT    NOT NULL,  -- 'approved' | 'rejected'
            reasons_json  TEXT    NOT NULL,  -- JSON array of reason strings
            decided_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_prompt_promotions_name
            ON prompt_promotions(prompt_name, decided_at DESC);
        """)
    _migrate_columns(conn)


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the initial schema — idempotent."""
    migrations = [
        ("eval_runs", "router_prompt_id", "TEXT"),
        ("eval_runs", "classified_as",    "TEXT"),
    ]
    for table, column, col_type in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # Column already exists
