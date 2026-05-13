"""
Database persistence for intake requests. Connects to Supabase (PostgreSQL)
via psycopg2. Falls back to env vars when Streamlit secrets are unavailable.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, Json


def get_connection():
    """Return a psycopg2 connection using Streamlit secrets or env vars."""
    try:
        import streamlit as st
        db_url = st.secrets.get("SUPABASE_DB_URL")
        if db_url:
            return psycopg2.connect(db_url)
        return psycopg2.connect(
            host=st.secrets["PGHOST"],
            user=st.secrets["PGUSER"],
            password=st.secrets["PGPASSWORD"],
            dbname=st.secrets["PGDATABASE"],
            port=st.secrets.get("PGPORT", 5432),
        )
    except Exception:
        db_url = os.environ.get("SUPABASE_DB_URL")
        if db_url:
            return psycopg2.connect(db_url)
        return psycopg2.connect(
            host=os.environ["PGHOST"],
            user=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"],
            dbname=os.environ["PGDATABASE"],
            port=os.environ.get("PGPORT", 5432),
        )


def init_db() -> None:
    """Create the intake_requests table if it doesn't exist."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS intake_requests (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ DEFAULT now(),
                    status TEXT NOT NULL DEFAULT 'submitted',
                    feature_name TEXT,
                    stakeholder_persona TEXT,
                    intake_record JSONB NOT NULL,
                    conversation_history JSONB NOT NULL,
                    readiness_score INTEGER,
                    feature_type_guess TEXT,
                    feature_type_confidence REAL,
                    copilot_recommendation JSONB,
                    pm_feature_type TEXT,
                    pm_boost_inputs TEXT,
                    pm_decision TEXT,
                    pm_rejection_reason TEXT,
                    pm_field_edits JSONB,
                    generator_input JSONB,
                    pipeline_result JSONB
                );
            """)
        conn.commit()
        print("Table 'intake_requests' is ready.")
    finally:
        conn.close()


def save_intake_request(copilot) -> str:
    """Persist a completed intake conversation. Returns the request UUID."""
    record = copilot.get_intake_record()
    recommendation = copilot.get_recommendation()

    request_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO intake_requests
                    (id, feature_name, intake_record, conversation_history,
                     readiness_score, feature_type_guess, feature_type_confidence,
                     copilot_recommendation)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    request_id,
                    record.feature_name.value or "Untitled Request",
                    Json(record.to_dict()),
                    Json(record.conversation_history),
                    record.readiness_score(),
                    record.feature_type.value or None,
                    record.feature_type_confidence,
                    Json(recommendation),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return request_id


def get_pending_requests() -> list[dict[str, Any]]:
    """Return submitted/in_review requests, newest first."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT id, created_at, feature_name, status, readiness_score,
                       feature_type_guess, feature_type_confidence,
                       copilot_recommendation, stakeholder_persona
                FROM intake_requests
                WHERE status IN ('submitted', 'in_review')
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_request(request_id: str) -> dict[str, Any] | None:
    """Return all columns for a single request, or None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM intake_requests WHERE id = %s", (request_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def update_request(request_id: str, **kwargs: Any) -> None:
    """Update arbitrary fields on a request; always refreshes updated_at."""
    kwargs["updated_at"] = datetime.utcnow()
    set_clauses = ", ".join(f"{k} = %s" for k in kwargs)
    values = list(kwargs.values()) + [request_id]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE intake_requests SET {set_clauses} WHERE id = %s",
                values,
            )
        conn.commit()
    finally:
        conn.close()
