"""
evaluation/prompt_governance.py

Governance gate for promoting prompt versions from candidate to production.

A promotion is approved only when all four requirements are met:
  (a) A/B evidence exists — runs using the candidate prompt AND runs using the
      current production prompt (or the v1 baseline), covering the same golden
      set cases.
  (b) Minimum golden set runs — at least GOVERNANCE_RULES["min_golden_set_runs"]
      eval_runs exist for the candidate prompt version.
  (c) Score improvement — candidate mean score exceeds production mean by at
      least GOVERNANCE_RULES["min_improvement_threshold"] points.
  (d) No category regression — no feature_type mean drops more than
      GOVERNANCE_RULES["regression_threshold"] points vs. production.

Checks run in order and fail fast — the first unmet requirement returns an
actionable rejection reason without running subsequent checks.

Prompt column mapping in eval_runs:
  reviewer / generator prompts → eval_runs.prompt_id
  router prompts               → eval_runs.router_prompt_id
  NULL router_prompt_id        → implicit router_v1 baseline (pre-migration runs)

CLI:
  python -m evaluation.prompt_governance --check <prompt_name> <candidate_version>
  python -m evaluation.prompt_governance --history
  python -m evaluation.prompt_governance --promote <prompt_name> <candidate_version>
  python -m evaluation.prompt_governance          # smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.eval_db import get_connection, init_db, DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Governance configuration
# ---------------------------------------------------------------------------

GOVERNANCE_RULES: dict[str, Any] = {
    # Must have eval runs using both the production and candidate prompt versions
    "promotion_requires_ab_test":    True,
    # Minimum number of eval_runs using the candidate prompt
    "min_golden_set_runs":           2,
    # Candidate mean score must exceed production mean by at least this many points
    "min_improvement_threshold":     2.0,
    # Roll back (reject) if any feature_type mean drops more than this vs. production
    "rollback_on_regression":        True,
    "regression_threshold":          -3.0,   # negative = allowed drop before flag
}


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------

def _resolve_prompt_id(conn, prompt_name: str, version: int) -> str | None:
    """Return the content-hash prompt_id for a given (name, version) pair."""
    row = conn.execute(
        "SELECT id FROM prompts WHERE name = ? AND version = ?",
        (prompt_name, version),
    ).fetchone()
    return row["id"] if row else None


def _prompt_column(conn, prompt_id: str) -> str:
    """
    Return the eval_runs column that links to this prompt_id.

    Router prompts → 'router_prompt_id'
    All others     → 'prompt_id'
    """
    row = conn.execute(
        "SELECT agent FROM prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    if row and row["agent"] == "router":
        return "router_prompt_id"
    return "prompt_id"


def _scores_for_prompt(
    conn,
    prompt_id: str | None,
    col: str,
) -> list[dict]:
    """
    Return all eval_run rows for the given prompt_id / column.

    Special case: when prompt_id is None and col is 'router_prompt_id',
    returns rows where router_prompt_id IS NULL (implicit router_v1 baseline).
    """
    if prompt_id is None and col == "router_prompt_id":
        rows = conn.execute(
            """
            SELECT golden_set_id, feature_type,
                   COALESCE(final_score, original_score) AS score
            FROM   eval_runs
            WHERE  router_prompt_id IS NULL
              AND  COALESCE(final_score, original_score) IS NOT NULL
            """
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT golden_set_id, feature_type,
                   COALESCE(final_score, original_score) AS score
            FROM   eval_runs
            WHERE  {col} = ?
              AND  COALESCE(final_score, original_score) IS NOT NULL
            """,
            (prompt_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _group_by_type(rows: list[dict]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for r in rows:
        result.setdefault(r["feature_type"], []).append(float(r["score"]))
    return result


# ---------------------------------------------------------------------------
# can_promote_prompt
# ---------------------------------------------------------------------------

def can_promote_prompt(
    db_path: Path,
    prompt_name: str,
    candidate_version: int,
) -> dict[str, Any]:
    """
    Check whether a prompt version meets governance requirements for promotion.

    Args:
        db_path:           Path to the eval SQLite DB.
        prompt_name:       Registered name, e.g. "router_v2", "reviewer_v1".
        candidate_version: Version integer of the candidate prompt to promote.

    Returns:
        {
            "approved":   bool,
            "reasons":    [str],   # one entry per check, pass or fail
            "evidence":   {
                "candidate_prompt_id":   str,
                "production_prompt_id":  str | None,
                "candidate_n":           int,
                "production_n":          int,
                "candidate_mean":        float,
                "production_mean":       float,
                "score_delta":           float,
                "category_deltas":       {type: float},
                "regression_types":      [str],
            },
        }
    """
    with get_connection(db_path) as conn:
        return _run_checks(conn, prompt_name, candidate_version)


def _run_checks(conn, prompt_name: str, candidate_version: int) -> dict[str, Any]:
    reasons: list[str] = []
    evidence: dict[str, Any] = {
        "candidate_prompt_id":   None,
        "production_prompt_id":  None,
        "candidate_n":           0,
        "production_n":          0,
        "candidate_mean":        0.0,
        "production_mean":       0.0,
        "score_delta":           0.0,
        "category_deltas":       {},
        "regression_types":      [],
    }

    # ── Resolve candidate prompt_id ──────────────────────────────────────────
    cand_id = _resolve_prompt_id(conn, prompt_name, candidate_version)
    if cand_id is None:
        reasons.append(
            f"FAIL: prompt '{prompt_name}' version {candidate_version} not found "
            "in the prompt registry. Register it with PromptRegistry.register() first."
        )
        return {"approved": False, "reasons": reasons, "evidence": evidence}

    evidence["candidate_prompt_id"] = cand_id
    col = _prompt_column(conn, cand_id)

    # ── Resolve current production version ───────────────────────────────────
    # Production = the highest version below candidate_version for the same base name.
    # For router: strip the version suffix and find the previous registered version.
    # We look in the prompts table for the same agent / same base name family.
    prod_row = conn.execute(
        """
        SELECT id, name, version FROM prompts
        WHERE  name != ?
          AND  agent = (SELECT agent FROM prompts WHERE id = ?)
        ORDER  BY version DESC
        LIMIT  1
        """,
        (prompt_name, cand_id),
    ).fetchone()

    # Fallback: if no other named prompt exists for this agent, production is the
    # NULL baseline (for router) or there is no production baseline yet.
    if prod_row:
        prod_id      = prod_row["id"]
        prod_version = prod_row["version"]
        prod_name    = prod_row["name"]
    else:
        prod_id      = None   # router NULL baseline
        prod_version = None
        prod_name    = "(implicit v1 baseline)"

    evidence["production_prompt_id"] = prod_id

    cand_rows = _scores_for_prompt(conn, cand_id, col)
    prod_rows = _scores_for_prompt(conn, prod_id, col)

    # For router prompts: if the resolved production prompt has no runs, fall back
    # to the NULL baseline (implicit router_v1 — runs from before router_prompt_id existed).
    if not prod_rows and col == "router_prompt_id":
        prod_rows = _scores_for_prompt(conn, None, col)
        if prod_rows:
            prod_id   = None
            prod_name = "(implicit NULL baseline)"
            evidence["production_prompt_id"] = None

    evidence["candidate_n"]  = len(cand_rows)
    evidence["production_n"] = len(prod_rows)

    # ── Check (a): A/B evidence ───────────────────────────────────────────────
    if GOVERNANCE_RULES["promotion_requires_ab_test"]:
        if len(cand_rows) == 0:
            reasons.append(
                f"FAIL [a/b test]: No eval runs found using candidate "
                f"'{prompt_name}' v{candidate_version} (id={cand_id[:12]}). "
                "Run the eval pipeline with this prompt version before promoting."
            )
            return {"approved": False, "reasons": reasons, "evidence": evidence}
        if len(prod_rows) == 0:
            reasons.append(
                f"FAIL [a/b test]: No baseline eval runs found for production "
                f"prompt '{prod_name}'. Cannot compare without a production baseline."
            )
            return {"approved": False, "reasons": reasons, "evidence": evidence}
        # Find overlapping golden set cases
        cand_cases = {r["golden_set_id"] for r in cand_rows}
        prod_cases = {r["golden_set_id"] for r in prod_rows}
        overlap    = cand_cases & prod_cases
        if not overlap:
            reasons.append(
                f"FAIL [a/b test]: Candidate and production runs cover different "
                f"golden set cases — no common cases to compare. "
                f"Candidate cases: {sorted(cand_cases)}. "
                f"Production cases: {sorted(prod_cases)}."
            )
            return {"approved": False, "reasons": reasons, "evidence": evidence}
        reasons.append(
            f"PASS [a/b test]: {len(cand_rows)} candidate runs and "
            f"{len(prod_rows)} production runs covering "
            f"{len(overlap)} shared golden set case(s)."
        )

    # ── Check (b): minimum runs ───────────────────────────────────────────────
    min_runs = int(GOVERNANCE_RULES["min_golden_set_runs"])
    if len(cand_rows) < min_runs:
        reasons.append(
            f"FAIL [min runs]: Only {len(cand_rows)} eval run(s) for the candidate "
            f"(need ≥ {min_runs}). Run more eval cases before promoting."
        )
        return {"approved": False, "reasons": reasons, "evidence": evidence}
    reasons.append(
        f"PASS [min runs]: {len(cand_rows)} candidate eval run(s) ≥ {min_runs} required."
    )

    # ── Compute means for checks (c) and (d) ─────────────────────────────────
    cand_mean = _mean([r["score"] for r in cand_rows])
    prod_mean = _mean([r["score"] for r in prod_rows])
    delta     = round(cand_mean - prod_mean, 2)

    evidence["candidate_mean"] = round(cand_mean, 2)
    evidence["production_mean"] = round(prod_mean, 2)
    evidence["score_delta"]     = delta

    # ── Check (c): score improvement ─────────────────────────────────────────
    threshold = float(GOVERNANCE_RULES["min_improvement_threshold"])
    if delta < threshold:
        reasons.append(
            f"FAIL [improvement]: Score delta {delta:+.2f} pts is below the "
            f"{threshold:+.1f}-pt improvement threshold "
            f"(candidate mean: {cand_mean:.1f}, production mean: {prod_mean:.1f})."
        )
        return {"approved": False, "reasons": reasons, "evidence": evidence}
    reasons.append(
        f"PASS [improvement]: Score delta {delta:+.2f} pts exceeds "
        f"the {threshold:+.1f}-pt threshold "
        f"(candidate: {cand_mean:.1f}, production: {prod_mean:.1f})."
    )

    # ── Check (d): category regression ───────────────────────────────────────
    if GOVERNANCE_RULES["rollback_on_regression"]:
        reg_threshold = float(GOVERNANCE_RULES["regression_threshold"])
        cand_by_type  = _group_by_type(cand_rows)
        prod_by_type  = _group_by_type(prod_rows)
        cat_deltas: dict[str, float] = {}
        regression_types: list[str] = []

        all_types = set(list(cand_by_type) + list(prod_by_type))
        for ftype in sorted(all_types):
            c_mean = _mean(cand_by_type.get(ftype, []))
            p_mean = _mean(prod_by_type.get(ftype, []))
            if c_mean == 0.0 and ftype not in cand_by_type:
                continue   # candidate has no runs for this type — skip
            if p_mean == 0.0 and ftype not in prod_by_type:
                continue   # production has no runs for this type — skip
            d = round(c_mean - p_mean, 2)
            cat_deltas[ftype] = d
            if d < reg_threshold:
                regression_types.append(ftype)

        evidence["category_deltas"]  = cat_deltas
        evidence["regression_types"] = regression_types

        if regression_types:
            reg_details = ", ".join(
                f"{t} ({cat_deltas[t]:+.2f} pts)" for t in regression_types
            )
            reasons.append(
                f"FAIL [regression]: Category mean dropped more than "
                f"{reg_threshold:.1f} pts for: {reg_details}. "
                "Fix category regression before promoting."
            )
            return {"approved": False, "reasons": reasons, "evidence": evidence}

        reasons.append(
            f"PASS [regression]: No category regressions beyond "
            f"{reg_threshold:.1f}-pt threshold. "
            f"Deltas: { {k: f'{v:+.2f}' for k, v in cat_deltas.items()} }."
        )

    return {"approved": True, "reasons": reasons, "evidence": evidence}


# ---------------------------------------------------------------------------
# get_promotion_history
# ---------------------------------------------------------------------------

def get_promotion_history(db_path: Path = DEFAULT_DB_PATH) -> list[dict]:
    """Return all past promotion decisions, newest first.

    Each entry:
        {id, prompt_name, from_version, to_version, decision, reasons, decided_at}
    """
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, prompt_name, from_version, to_version,
                   decision, reasons_json, decided_at
            FROM   prompt_promotions
            ORDER  BY decided_at DESC, id DESC
            """
        ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        try:
            entry["reasons"] = json.loads(entry.pop("reasons_json"))
        except (json.JSONDecodeError, KeyError):
            entry["reasons"] = []
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# record_promotion
# ---------------------------------------------------------------------------

def record_promotion(
    db_path: Path,
    prompt_name: str,
    from_version: int | None,
    to_version: int,
    decision: str,
    reasons: list[str],
) -> int:
    """Log a promotion decision to prompt_promotions.

    Args:
        prompt_name:   Prompt name, e.g. "router_v2".
        from_version:  Current production version (None if first promotion).
        to_version:    Candidate version being promoted.
        decision:      "approved" or "rejected".
        reasons:       List of reason strings from can_promote_prompt().

    Returns:
        The AUTOINCREMENT id of the inserted row.
    """
    decided_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO prompt_promotions
                   (prompt_name, from_version, to_version, decision,
                    reasons_json, decided_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                prompt_name,
                from_version,
                to_version,
                decision,
                json.dumps(reasons),
                decided_at,
            ),
        )
        return cur.lastrowid


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_W = 70
_ICONS = {"PASS": "✓", "FAIL": "✗"}


def _print_decision(result: dict, prompt_name: str, candidate_version: int) -> None:
    print("=" * _W)
    print(f"  PROMOTION CHECK — {prompt_name}  →  v{candidate_version}")
    print("=" * _W)

    overall = "APPROVED" if result["approved"] else "REJECTED"
    print(f"\n  Decision: {overall}\n")

    for reason in result["reasons"]:
        tag  = "PASS" if reason.startswith("PASS") else "FAIL"
        icon = _ICONS[tag]
        # Wrap long reasons
        import textwrap
        lines = textwrap.wrap(reason, width=_W - 6)
        for i, line in enumerate(lines):
            prefix = f"  {icon} " if i == 0 else "    "
            print(f"{prefix}{line}")

    ev = result["evidence"]
    print(f"\n  Evidence:")
    print(f"    Candidate  id={str(ev['candidate_prompt_id'])[:12]}  n={ev['candidate_n']}  mean={ev['candidate_mean']:.1f}")
    print(f"    Production id={str(ev['production_prompt_id'])[:12]}  n={ev['production_n']}  mean={ev['production_mean']:.1f}")
    print(f"    Score delta: {ev['score_delta']:+.2f} pts")
    if ev.get("category_deltas"):
        print(f"    Category deltas: " +
              "  ".join(f"{k}: {v:+.2f}" for k, v in ev["category_deltas"].items()))
    if ev.get("regression_types"):
        print(f"    Regressions: {ev['regression_types']}")
    print("=" * _W)


def _print_history(history: list[dict]) -> None:
    print("=" * _W)
    print("  PROMPT PROMOTION HISTORY")
    print("=" * _W)
    if not history:
        print("  (no promotion decisions recorded yet)")
        return
    print(f"\n  {'#':>3}  {'Prompt':<18}  {'v_from':>6}  {'v_to':>4}  {'Decision':<10}  {'Decided at'}")
    print(f"  {'-' * 62}")
    for entry in history:
        from_v = str(entry["from_version"]) if entry["from_version"] is not None else "—"
        print(
            f"  {entry['id']:>3}  {entry['prompt_name']:<18}  {from_v:>6}  "
            f"{entry['to_version']:>4}  {entry['decision']:<10}  {entry['decided_at']}"
        )
    print()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Verify governance logic against mock DB data — no live DB required."""
    import tempfile
    import uuid

    failures: list[str] = []
    width = _W

    print("=" * width)
    print("  PROMPT GOVERNANCE — smoke test")
    print("=" * width)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_governance.db"
        init_db(db_path)

        with get_connection(db_path) as conn:
            # Register two prompt versions
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("prod_id_000001", "reviewer_v1", 1, "reviewer", "Production prompt text v1"),
            )
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("cand_id_000002", "reviewer_v2", 2, "reviewer", "Candidate prompt text v2"),
            )

            def _insert_run(golden_set_id, ftype, score, prompt_id):
                conn.execute(
                    """INSERT INTO eval_runs
                       (id, golden_set_id, feature_type, prompt_id,
                        original_score, final_score, passed, scorecard)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), golden_set_id, ftype, prompt_id,
                     score, score, 1 if score >= 65 else 0, "{}"),
                )

            # Production runs (reviewer_v1): mean ~75
            _insert_run("cap_001_bare",     "CAPABILITY", 74, "prod_id_000001")
            _insert_run("cap_001_boosted",  "CAPABILITY", 78, "prod_id_000001")
            _insert_run("web_001_bare",     "WEBPAGE",    68, "prod_id_000001")
            _insert_run("web_001_boosted",  "WEBPAGE",    80, "prod_id_000001")

        # ── Test A: approve — good delta, no regression ────────────────────
        print("\n[A] Approval: candidate v2 clearly better (+8 pts, no regression)")
        with get_connection(db_path) as conn:
            for golden_id, ftype, score in [
                ("cap_001_bare",    "CAPABILITY", 82),
                ("cap_001_boosted", "CAPABILITY", 86),
                ("web_001_bare",    "WEBPAGE",    77),
                ("web_001_boosted", "WEBPAGE",    88),
            ]:
                conn.execute(
                    """INSERT INTO eval_runs
                       (id, golden_set_id, feature_type, prompt_id,
                        original_score, final_score, passed, scorecard)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), golden_id, ftype, "cand_id_000002",
                     score, score, 1, "{}"),
                )

        result_a = can_promote_prompt(db_path, "reviewer_v2", 2)
        ok = result_a["approved"] is True
        print(f"  [{'PASS' if ok else 'FAIL'}] approved=True  delta={result_a['evidence']['score_delta']:+.2f}")
        if not ok:
            failures.append(f"[A] Expected approved=True, got False. Reasons: {result_a['reasons']}")

        # ── Test B: reject — insufficient runs ────────────────────────────
        print("\n[B] Rejection: candidate has only 1 run (min=2)")
        with get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("thin_cand_003", "reviewer_v3", 3, "reviewer", "Thin candidate v3 prompt"),
            )
            conn.execute(
                """INSERT INTO eval_runs
                   (id, golden_set_id, feature_type, prompt_id,
                    original_score, final_score, passed, scorecard)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), "cap_001_bare", "CAPABILITY", "thin_cand_003",
                 90, 90, 1, "{}"),
            )

        result_b = can_promote_prompt(db_path, "reviewer_v3", 3)
        ok = result_b["approved"] is False and any("min runs" in r for r in result_b["reasons"])
        print(f"  [{'PASS' if ok else 'FAIL'}] rejected for insufficient runs")
        if not ok:
            failures.append(f"[B] Expected rejection for min runs, got: {result_b['reasons']}")

        # ── Test C: reject — category regression ──────────────────────────
        # Use a separate agent ("generator") so production resolves cleanly to gen_v1.
        # Overall mean: (90+92+60+72)/4 = 78.5 vs prod (74+78+68+80)/4 = 75.0 → +3.5 (passes)
        # WEBPAGE mean: (60+72)/2 = 66 vs prod (68+80)/2 = 74 → -8 pts (fails regression)
        print("\n[C] Rejection: candidate gen_v2 regresses WEBPAGE by -8 pts")
        with get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("gen_prod_0001", "generator_v1", 1, "generator", "Generator production v1"),
            )
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("gen_cand_0002", "generator_v2", 2, "generator", "Generator candidate v2"),
            )
            # Production runs: generator_v1, mean=75
            for golden_id, ftype, score in [
                ("cap_001_bare",    "CAPABILITY", 74),
                ("cap_001_boosted", "CAPABILITY", 78),
                ("web_001_bare",    "WEBPAGE",    68),
                ("web_001_boosted", "WEBPAGE",    80),
            ]:
                conn.execute(
                    """INSERT INTO eval_runs
                       (id, golden_set_id, feature_type, prompt_id,
                        original_score, final_score, passed, scorecard)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), golden_id, ftype, "gen_prod_0001",
                     score, score, 1, "{}"),
                )
            # Candidate runs: generator_v2 — overall +3.5 but WEBPAGE -8
            for golden_id, ftype, score in [
                ("cap_001_bare",    "CAPABILITY", 90),
                ("cap_001_boosted", "CAPABILITY", 92),
                ("web_001_bare",    "WEBPAGE",    60),
                ("web_001_boosted", "WEBPAGE",    72),
            ]:
                conn.execute(
                    """INSERT INTO eval_runs
                       (id, golden_set_id, feature_type, prompt_id,
                        original_score, final_score, passed, scorecard)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), golden_id, ftype, "gen_cand_0002",
                     score, score, 1, "{}"),
                )

        result_c = can_promote_prompt(db_path, "generator_v2", 2)
        ok = (
            result_c["approved"] is False
            and any("regression" in r.lower() for r in result_c["reasons"])
            and "WEBPAGE" in result_c["evidence"]["regression_types"]
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] rejected for WEBPAGE regression  "
              f"deltas={result_c['evidence'].get('category_deltas', {})}")
        if not ok:
            failures.append(f"[C] Expected WEBPAGE regression rejection, got: {result_c['reasons']}")

        # ── Test D: record_promotion + get_promotion_history ──────────────
        print("\n[D] record_promotion and get_promotion_history")
        row_id = record_promotion(
            db_path, "reviewer_v2",
            from_version=1, to_version=2,
            decision="approved",
            reasons=result_a["reasons"],
        )
        record_promotion(
            db_path, "reviewer_v3",
            from_version=2, to_version=3,
            decision="rejected",
            reasons=result_b["reasons"],
        )

        history = get_promotion_history(db_path)
        ok = len(history) == 2 and history[0]["decision"] == "rejected"
        print(f"  [{'PASS' if ok else 'FAIL'}] history has {len(history)} entries, newest-first order correct")
        if not ok:
            failures.append(f"[D] history={history}")

        ok = isinstance(history[0]["reasons"], list) and len(history[0]["reasons"]) > 0
        print(f"  [{'PASS' if ok else 'FAIL'}] reasons deserialized as list")
        if not ok:
            failures.append(f"[D] reasons not list: {history[0]['reasons']}")

        # ── Test E: reject — improvement below threshold ──────────────────
        print("\n[E] Rejection: candidate v5 only improves +1 pt (threshold=+2)")
        with get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO prompts (id, name, version, agent, system_prompt)
                   VALUES (?, ?, ?, ?, ?)""",
                ("marginal_cand_005", "reviewer_v5", 5, "reviewer", "Marginal candidate v5"),
            )
            prod_mean = (74 + 78 + 68 + 80) / 4   # = 75.0
            for golden_id, ftype, score in [
                ("cap_001_bare",    "CAPABILITY", round(prod_mean + 0.5)),
                ("cap_001_boosted", "CAPABILITY", round(prod_mean + 1.0)),
                ("web_001_bare",    "WEBPAGE",    round(prod_mean + 1.5)),
                ("web_001_boosted", "WEBPAGE",    round(prod_mean + 1.0)),
            ]:
                conn.execute(
                    """INSERT INTO eval_runs
                       (id, golden_set_id, feature_type, prompt_id,
                        original_score, final_score, passed, scorecard)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), golden_id, ftype, "marginal_cand_005",
                     score, score, 1, "{}"),
                )

        result_e = can_promote_prompt(db_path, "reviewer_v5", 5)
        ok = (
            result_e["approved"] is False
            and any("improvement" in r.lower() for r in result_e["reasons"])
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] rejected for insufficient improvement  "
              f"delta={result_e['evidence']['score_delta']:+.2f}")
        if not ok:
            failures.append(f"[E] Expected improvement rejection, got: {result_e['reasons']}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * width}")
    if failures:
        print(f"  RESULT: {len(failures)} failure(s)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: all checks passed")
    print("=" * width)

    raise SystemExit(1 if failures else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Prompt promotion governance for SAFe Feature Spec pipeline"
    )
    parser.add_argument(
        "--check",
        nargs=2,
        metavar=("PROMPT_NAME", "CANDIDATE_VERSION"),
        help="Check governance requirements for promoting a prompt version",
    )
    parser.add_argument(
        "--promote",
        nargs=2,
        metavar=("PROMPT_NAME", "CANDIDATE_VERSION"),
        help="Run governance check and record the decision if approved",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Show past promotion decisions",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to eval SQLite DB",
    )
    args = parser.parse_args()

    # No flags → smoke test
    if not args.check and not args.promote and not args.history:
        _smoke_test()

    db_path = Path(args.db)
    init_db(db_path)

    if args.history:
        history = get_promotion_history(db_path)
        _print_history(history)
        sys.exit(0)

    if args.check or args.promote:
        name_ver = args.check or args.promote
        prompt_name       = name_ver[0]
        candidate_version = int(name_ver[1])

        result = can_promote_prompt(db_path, prompt_name, candidate_version)
        _print_decision(result, prompt_name, candidate_version)

        if args.promote:
            # Resolve production version for from_version
            with get_connection(db_path) as conn:
                prod_row = conn.execute(
                    """
                    SELECT version FROM prompts
                    WHERE  name != ?
                      AND  agent = (SELECT agent FROM prompts
                                    WHERE name = ? AND version = ?)
                    ORDER  BY version DESC LIMIT 1
                    """,
                    (prompt_name, prompt_name, candidate_version),
                ).fetchone()
            from_version = prod_row["version"] if prod_row else None

            decision = "approved" if result["approved"] else "rejected"
            row_id   = record_promotion(
                db_path, prompt_name,
                from_version=from_version,
                to_version=candidate_version,
                decision=decision,
                reasons=result["reasons"],
            )
            print(f"\n  Recorded promotion decision (id={row_id}).")
            if result["approved"]:
                print("  → Update your pipeline to use this prompt version.")
            else:
                print("  → Address the failing checks before re-running --promote.")

        sys.exit(0 if result["approved"] else 1)
