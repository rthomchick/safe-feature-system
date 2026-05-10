"""
connectors/postgres.py

PostgreSQL (and SQLite fallback) implementation of ConnectorInterface.

Uses get_connection() from eval_db, so it inherits the same dual-mode
behavior: PostgreSQL when DATABASE_URL is set, SQLite for local dev and tests.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from connectors.base import ConnectorInterface, FeatureRequest
from evaluation.eval_db import get_connection, is_postgres


def _ph(db_path=None) -> str:
    """Parameter placeholder for the active database backend."""
    return "%s" if is_postgres(db_path) else "?"


def _now_expr(db_path=None) -> str:
    """SQL expression for the current timestamp."""
    return "NOW()" if is_postgres(db_path) else "CURRENT_TIMESTAMP"


def _row_to_request(row: dict) -> FeatureRequest:
    """Convert a DB row dict to a FeatureRequest."""
    boost_raw = row.get("boost_inputs") or "{}"
    boost = json.loads(boost_raw) if isinstance(boost_raw, str) else (boost_raw or {})

    completed_at = row.get("completed_at")
    if isinstance(completed_at, str):
        # SQLite returns ISO strings; normalize to datetime
        try:
            completed_at = datetime.fromisoformat(completed_at)
        except (ValueError, TypeError):
            completed_at = None

    return FeatureRequest(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        notes=row.get("notes") or "",
        feature_type=row.get("feature_type"),
        status=row.get("status", "draft"),
        boost_inputs=boost,
        generated_spec=row.get("generated_spec"),
        score=row.get("score"),
        run_cost=row.get("run_cost"),
        run_id=row.get("run_id"),
        completed_at=completed_at,
    )


class PostgresConnector(ConnectorInterface):
    """Read/write feature requests from the eval pipeline database.

    Uses the same dual-mode connection as the rest of the pipeline:
    PostgreSQL when DATABASE_URL is set, SQLite when db_path is provided.

    Args:
        db_path: Explicit SQLite path for local dev or tests. Pass None to
                 use PostgreSQL (requires DATABASE_URL).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_pending(self) -> list[FeatureRequest]:
        """Return all requests with status 'ready', oldest first."""
        ph = _ph(self.db_path)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM feature_requests WHERE status = {ph} ORDER BY created_at ASC",
                ("ready",),
            ).fetchall()
        return [_row_to_request(dict(r)) for r in rows]

    def get_request(self, request_id: str) -> Optional[FeatureRequest]:
        """Fetch a single request by ID. Returns None if not found."""
        ph = _ph(self.db_path)
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT * FROM feature_requests WHERE id = {ph}",
                (request_id,),
            ).fetchone()
        return _row_to_request(dict(row)) if row else None

    def list_completed(self, limit: int = 20) -> list[FeatureRequest]:
        """Return completed requests, newest first."""
        ph = _ph(self.db_path)
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""SELECT * FROM feature_requests
                    WHERE status = {ph}
                    ORDER BY completed_at DESC
                    LIMIT {ph}""",
                ("complete", limit),
            ).fetchall()
        return [_row_to_request(dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_request(self, request: FeatureRequest) -> str:
        """Insert a new feature request. Returns the assigned ID."""
        assigned_id = request.id or str(uuid.uuid4())
        ph = _ph(self.db_path)
        with get_connection(self.db_path) as conn:
            conn.execute(
                f"""INSERT INTO feature_requests
                    (id, title, description, notes, feature_type, status, boost_inputs)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                (
                    assigned_id,
                    request.title,
                    request.description,
                    request.notes or "",
                    request.feature_type,
                    request.status,
                    json.dumps(request.boost_inputs),
                ),
            )
        return assigned_id

    def update_status(self, request_id: str, status: str) -> None:
        """Update the status of a request."""
        ph = _ph(self.db_path)
        with get_connection(self.db_path) as conn:
            conn.execute(
                f"UPDATE feature_requests SET status = {ph} WHERE id = {ph}",
                (status, request_id),
            )

    def write_result(
        self,
        request_id: str,
        spec: str,
        score: int,
        cost: float,
        run_id: str,
    ) -> None:
        """Write pipeline output back to the request and mark it complete."""
        ph = _ph(self.db_path)
        now_expr = _now_expr(self.db_path)
        with get_connection(self.db_path) as conn:
            conn.execute(
                f"""UPDATE feature_requests
                    SET generated_spec = {ph},
                        score          = {ph},
                        run_cost       = {ph},
                        run_id         = {ph},
                        status         = {ph},
                        completed_at   = {now_expr}
                    WHERE id = {ph}""",
                (spec, score, cost, run_id, "complete", request_id),
            )
