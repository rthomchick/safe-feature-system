# evaluation/result_store.py
from __future__ import annotations
# ResultStore: read/write interface for eval_runs and related token_usage rows.
#
# Each eval run corresponds to one full pipeline execution against a golden-set
# entry. The scorecard is the raw JSON dict returned by review_feature_spec().

import json
import uuid
from pathlib import Path

from evaluation.eval_db import get_connection, DEFAULT_DB_PATH


class ResultStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_run(
        self,
        golden_set_id: str,
        feature_type: str,
        scorecard: dict,
        *,
        run_id: str | None = None,
        prompt_id: str | None = None,
        router_prompt_id: str | None = None,
        classified_as: str | None = None,
        original_score: int | None = None,
        final_score: int | None = None,
        passed: bool | None = None,
    ) -> str:
        """Persist one eval run. Returns the run_id (auto-generated if not supplied).

        Args:
            golden_set_id:    Matches the 'id' field in golden_set.GOLDEN_SET.
            feature_type:     CAPABILITY, EXPERIENCE, or WEBPAGE.
            scorecard:        The dict returned by review_feature_spec() — stored as JSON.
            run_id:           Optional caller-supplied UUID; one is generated if omitted.
            prompt_id:        FK to prompts.id for the reviewer prompt used.
            router_prompt_id: FK to prompts.id for the router prompt used.
            classified_as:    The type the router actually returned (for routing accuracy).
            original_score:   Score before improvement pass.
            final_score:      Score after improvement pass.
            passed:           Whether the run met the golden-set's min_final_score.

        Returns:
            run_id string.
        """
        run_id = run_id or str(uuid.uuid4())
        with get_connection(self.db_path) as conn:
            conn.execute(
                """INSERT INTO eval_runs
                   (id, golden_set_id, feature_type, prompt_id,
                    router_prompt_id, classified_as,
                    original_score, final_score, passed, scorecard)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    golden_set_id,
                    feature_type,
                    prompt_id,
                    router_prompt_id,
                    classified_as,
                    original_score,
                    final_score,
                    int(passed) if passed is not None else None,
                    json.dumps(scorecard),
                ),
            )
        return run_id

    # ------------------------------------------------------------------
    # Read — runs
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> dict | None:
        """Fetch a single run by id. scorecard is deserialized to dict."""
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            return self._deserialize(dict(row))

    def get_runs_for_golden(self, golden_set_id: str) -> list[dict]:
        """All runs for a golden-set entry, newest first."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM eval_runs
                   WHERE golden_set_id = ?
                   ORDER BY run_at DESC""",
                (golden_set_id,),
            ).fetchall()
            return [self._deserialize(dict(r)) for r in rows]

    def latest_scores(self, golden_set_id: str) -> dict | None:
        """Convenience: most recent original/final scores for a golden-set entry.

        Returns None if no runs exist yet.
        """
        runs = self.get_runs_for_golden(golden_set_id)
        if not runs:
            return None
        r = runs[0]
        return {
            "run_id":         r["id"],
            "run_at":         r["run_at"],
            "original_score": r["original_score"],
            "final_score":    r["final_score"],
            "passed":         bool(r["passed"]) if r["passed"] is not None else None,
        }

    # ------------------------------------------------------------------
    # Read — token usage
    # ------------------------------------------------------------------

    def get_token_usage(self, run_id: str) -> list[dict]:
        """All token_usage rows for a run, in call order."""
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM token_usage
                   WHERE run_id = ?
                   ORDER BY call_at ASC, id ASC""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def token_summary(self, run_id: str) -> dict:
        """Aggregated token totals for a run (re-derived from stored rows)."""
        rows = self.get_token_usage(run_id)
        total_in  = sum(r["input_tokens"]  for r in rows)
        total_out = sum(r["output_tokens"] for r in rows)
        return {
            "run_id":        run_id,
            "calls":         len(rows),
            "input_tokens":  total_in,
            "output_tokens": total_out,
            "by_agent": _group_by_agent(rows),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _deserialize(row: dict) -> dict:
        if row.get("scorecard"):
            row["scorecard"] = json.loads(row["scorecard"])
        return row


def _group_by_agent(rows: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for r in rows:
        agent = r["agent"]
        if agent not in result:
            result[agent] = {"input": 0, "output": 0, "calls": 0}
        result[agent]["input"]  += r["input_tokens"]
        result[agent]["output"] += r["output_tokens"]
        result[agent]["calls"]  += 1
    return result
