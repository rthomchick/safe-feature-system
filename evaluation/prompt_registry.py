# evaluation/prompt_registry.py
from __future__ import annotations
# PromptRegistry: content-addressed, versioned store for system prompts.
#
# Each unique system_prompt text gets a stable id (SHA-256 prefix) so the
# same prompt content always maps to the same row — registering twice is safe.
# Distinct content under the same name gets an incrementing version number,
# making prompt evolution queryable.

import hashlib
from pathlib import Path

from evaluation.eval_db import get_connection, is_postgres


def _ph() -> str:
    """Parameter placeholder for the active database backend."""
    return "%s" if is_postgres() else "?"


class PromptRegistry:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def register(self, name: str, agent: str, system_prompt: str) -> str:
        """Register a system prompt. Returns its stable prompt_id.

        Idempotent: registering the same text twice returns the same id
        without creating a duplicate row or bumping the version counter.

        Args:
            name:          Human-readable label (e.g. "reviewer_v2").
            agent:         Pipeline stage that owns the prompt (e.g. "reviewer").
            system_prompt: The full system prompt text.

        Returns:
            16-char hex prompt_id derived from the prompt content.
        """
        prompt_id = self._content_id(system_prompt)
        ph = _ph()
        with get_connection(self.db_path) as conn:
            existing = conn.execute(
                f"SELECT id FROM prompts WHERE id = {ph}", (prompt_id,)
            ).fetchone()
            if existing:
                return prompt_id

            row = conn.execute(
                f"SELECT MAX(version) AS max_ver FROM prompts WHERE name = {ph}", (name,)
            ).fetchone()
            version = (row["max_ver"] or 0) + 1

            conn.execute(
                f"""INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph})""",
                (prompt_id, name, version, agent, system_prompt),
            )
        return prompt_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, prompt_id: str) -> dict | None:
        """Fetch a prompt by its content-addressed id."""
        ph = _ph()
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT * FROM prompts WHERE id = {ph}", (prompt_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_latest(self, name: str) -> dict | None:
        """Fetch the highest-version prompt registered under a given name."""
        ph = _ph()
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                f"SELECT * FROM prompts WHERE name = {ph} ORDER BY version DESC LIMIT 1",
                (name,),
            ).fetchone()
            return dict(row) if row else None

    def list_versions(self, name: str) -> list[dict]:
        """Return all versions of a prompt, oldest first."""
        ph = _ph()
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM prompts WHERE name = {ph} ORDER BY version ASC", (name,)
            ).fetchall()
            return [dict(r) for r in rows]

    def list_agents(self) -> list[str]:
        """Return all distinct agent names that have registered prompts."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT agent FROM prompts ORDER BY agent"
            ).fetchall()
            return [r["agent"] for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _content_id(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
