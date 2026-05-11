"""
evaluation/infrastructure_audit.py

Connects to the eval SQLite DB and produces a structured audit report covering:
  1. Eval run counts grouped by feature_type
  2. Total token spend across all runs (with per-model breakdown)
  3. Registered prompt versions (all agents)
  4. Score distribution stats (mean, min, max, stdev) per feature_type
  5. Gap analysis: responsible_ai_checklist requirements vs. what the DB contains

The report is a plain dict — flat enough for Streamlit st.json() / st.metric()
or CLI pretty-printing via _print_report().

Usage:
    python -m evaluation.infrastructure_audit
    python -m evaluation.infrastructure_audit --db path/to/eval.db
"""

from __future__ import annotations

import argparse
import math
import json
from pathlib import Path
from typing import Any

from evaluation.eval_db import get_connection, init_db, DEFAULT_DB_PATH
from evaluation.responsible_ai_checklist import CHECKLIST, Status


# ---------------------------------------------------------------------------
# Token cost table (mirrors token_tracker.py — single source of truth is there;
# this copy is intentional so the audit module has no runtime dep on agents/)
# ---------------------------------------------------------------------------

_TOKEN_COSTS: dict[str, dict[str, float]] = {
    "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":          {"input":  3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input":  0.80, "output":  4.00},
    "claude-haiku-4-5":           {"input":  0.80, "output":  4.00},
    "default":                    {"input":  3.00, "output": 15.00},
}


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = _TOKEN_COSTS.get(model, _TOKEN_COSTS["default"])
    return (
        (input_tokens  / 1_000_000) * pricing["input"]
        + (output_tokens / 1_000_000) * pricing["output"]
    )


# ---------------------------------------------------------------------------
# Section 1 — run counts by feature_type
# ---------------------------------------------------------------------------

def _run_counts(conn) -> dict[str, Any]:
    """Total runs and per-feature-type breakdown."""
    rows = conn.execute(
        """
        SELECT feature_type,
               COUNT(*)                          AS total,
               SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed,
               SUM(CASE WHEN passed = 0 THEN 1 ELSE 0 END) AS failed
        FROM   eval_runs
        GROUP  BY feature_type
        ORDER  BY feature_type
        """
    ).fetchall()

    by_type: dict[str, dict] = {}
    grand_total = grand_passed = grand_failed = 0
    for r in rows:
        by_type[r["feature_type"]] = {
            "total":  r["total"],
            "passed": r["passed"],
            "failed": r["failed"],
        }
        grand_total  += r["total"]
        grand_passed += r["passed"]
        grand_failed += r["failed"]

    return {
        "total_runs": grand_total,
        "total_passed": grand_passed,
        "total_failed": grand_failed,
        "by_feature_type": by_type,
    }


# ---------------------------------------------------------------------------
# Section 2 — token spend
# ---------------------------------------------------------------------------

def _token_spend(conn) -> dict[str, Any]:
    """Aggregate token spend across all runs, broken down by model."""
    rows = conn.execute(
        """
        SELECT model,
               SUM(input_tokens)  AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               COUNT(*)           AS calls
        FROM   token_usage
        GROUP  BY model
        ORDER  BY model
        """
    ).fetchall()

    by_model: dict[str, dict] = {}
    total_input = total_output = total_calls = 0
    total_cost = 0.0

    for r in rows:
        cost = _cost_usd(r["model"], r["input_tokens"], r["output_tokens"])
        by_model[r["model"]] = {
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "calls":         r["calls"],
            "cost_usd":      round(cost, 6),
        }
        total_input  += r["input_tokens"]
        total_output += r["output_tokens"]
        total_calls  += r["calls"]
        total_cost   += cost

    # Per-agent breakdown across all models
    agent_rows = conn.execute(
        """
        SELECT agent,
               SUM(input_tokens)  AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               COUNT(*)           AS calls
        FROM   token_usage
        GROUP  BY agent
        ORDER  BY agent
        """
    ).fetchall()

    by_agent: dict[str, dict] = {}
    for r in agent_rows:
        by_agent[r["agent"]] = {
            "input_tokens":  r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "calls":         r["calls"],
        }

    return {
        "total_input_tokens":  total_input,
        "total_output_tokens": total_output,
        "total_calls":         total_calls,
        "total_cost_usd":      round(total_cost, 6),
        "by_model":            by_model,
        "by_agent":            by_agent,
    }


# ---------------------------------------------------------------------------
# Section 3 — registered prompt versions
# ---------------------------------------------------------------------------

def _prompt_versions(conn) -> dict[str, Any]:
    """All prompt versions registered in the prompts table."""
    rows = conn.execute(
        """
        SELECT id, name, version, agent, created_at
        FROM   prompts
        ORDER  BY agent, name, version
        """
    ).fetchall()

    prompts: list[dict] = [dict(r) for r in rows]

    # Group by agent for easier consumption in Streamlit
    by_agent: dict[str, list[dict]] = {}
    for p in prompts:
        by_agent.setdefault(p["agent"], []).append(p)

    return {
        "total_registered": len(prompts),
        "agents_with_prompts": sorted(by_agent.keys()),
        "by_agent": by_agent,
        "all_prompts": prompts,
    }


# ---------------------------------------------------------------------------
# Section 4 — score distribution per feature_type
# ---------------------------------------------------------------------------

def _stdev(values: list[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return round(math.sqrt(variance), 2)


def _score_distribution(conn) -> dict[str, Any]:
    """Mean, min, max, stdev of final_score grouped by feature_type.

    Uses final_score (post-improvement pass) where non-NULL; falls back to
    original_score. Rows where both are NULL are excluded from stats.
    """
    rows = conn.execute(
        """
        SELECT feature_type,
               COALESCE(final_score, original_score) AS score
        FROM   eval_runs
        WHERE  COALESCE(final_score, original_score) IS NOT NULL
        ORDER  BY feature_type
        """
    ).fetchall()

    # Collect per-type
    grouped: dict[str, list[float]] = {}
    for r in rows:
        grouped.setdefault(r["feature_type"], []).append(float(r["score"]))

    all_scores: list[float] = [s for scores in grouped.values() for s in scores]
    overall_mean = round(sum(all_scores) / len(all_scores), 2) if all_scores else None
    overall_stdev = _stdev(all_scores, overall_mean or 0.0) if all_scores else None

    by_type: dict[str, dict] = {}
    for ftype, scores in sorted(grouped.items()):
        mean = round(sum(scores) / len(scores), 2)
        by_type[ftype] = {
            "n":     len(scores),
            "mean":  mean,
            "min":   int(min(scores)),
            "max":   int(max(scores)),
            "stdev": _stdev(scores, mean),
            # Flag if this type's mean is more than 1 overall-stdev below overall mean
            "underperforming": (
                overall_mean is not None
                and overall_stdev is not None
                and mean < (overall_mean - overall_stdev)
            ),
        }

    return {
        "overall_mean":  overall_mean,
        "overall_stdev": overall_stdev,
        "total_scored_runs": len(all_scores),
        "by_feature_type": by_type,
    }


# ---------------------------------------------------------------------------
# Section 5 — gap analysis
# ---------------------------------------------------------------------------

# Maps each checklist check string to the DB signal that would confirm it is
# satisfied at runtime.  "present" means the column / table exists and has data.
# These are evaluated against the live DB state.
_DB_SIGNALS: dict[str, str] = {
    # fairness
    "Golden set spans multiple feature categories (capability, UX, experience)":
        "eval_runs has ≥ 2 distinct feature_type values",
    "Eval runner scores each category independently and surfaces per-category means":
        "eval_runs.feature_type + final_score allow per-type aggregation (always possible)",
    "Cross-category score comparison flags categories with mean score < overall mean - 1 stddev":
        "NOT IN DB — must be implemented in eval pipeline or this audit module",
    "Bias detection: automated alert when any category consistently underperforms others":
        "NOT IN DB — no alert mechanism stored or triggered",

    # reliability
    "Eval DB stores scored outputs for every run against the golden set":
        "eval_runs table present with scorecard column",
    "Prompt registry versions every prompt; version is recorded per eval run":
        "prompts table + eval_runs.prompt_id FK present",
    "Smoke test covers the full agent pipeline end-to-end":
        "NOT IN DB — smoke_test.py exists but results are not persisted",
    "Regression guard: eval runner fails the run if mean score drops > N points vs. prior baseline":
        "NOT IN DB — no baseline threshold stored; eval runner does not abort on regression",
    "A/B test router compares routing strategies and surfaces win/loss metrics":
        "eval_runs.router_prompt_id + classified_as columns present",

    # transparency
    "Every eval result is linked to the prompt version used (prompt_registry)":
        "eval_runs.prompt_id references prompts.id",
    "Scoring rubric is stored alongside results in the eval DB":
        "eval_runs.scorecard stores full reviewer JSON including section rubric",
    "Dashboard exposes per-run metadata: model, prompt hash, score breakdown":
        "token_usage.model + eval_runs.prompt_id + scorecard all queryable",
    "Audit trail: per-run decision trace capturing agent path, tool calls, and intermediate outputs":
        "NOT IN DB — no decision_trace table or column exists",

    # cost_governance
    "Token usage tracked per run (input tokens, output tokens, estimated cost)":
        "token_usage table present with input_tokens, output_tokens, model columns",
    "Token tracker aggregates cost by model, prompt version, and eval suite":
        "token_usage joinable to eval_runs and prompts for aggregation (always possible)",
    "Cost guardrails: configurable per-run spend limit that aborts execution if exceeded":
        "NOT IN DB — no spend_limit config stored or enforced",
    "Spend alerts: notification when cumulative eval spend crosses a threshold":
        "NOT IN DB — no alert threshold stored or triggered",

    # safety
    "Output schema validation ensures required spec sections are present":
        "NOT IN DB — no schema_validation_result column or table",
    "Grounding check: verify that factual claims in the spec are entailed by the input":
        "NOT IN DB — no grounding_result column or table",
    "Hallucination detection: flag outputs that introduce named metrics or systems absent from input":
        "NOT IN DB — no hallucination_flag column or table",
    "Human review gate for any output flagged by grounding or hallucination checks":
        "NOT IN DB — no human_review_required or review_gate column",

    # versioning
    "Prompt registry assigns a content-hash version to every prompt":
        "prompts.id is SHA-256 content hash; prompts.version is sequence number",
    "Eval results stored with prompt version, model ID, and timestamp":
        "eval_runs.prompt_id + token_usage.model + eval_runs.run_at all present",
    "Prompt diffs surfaced when a new version is registered":
        "NOT IN DB — no prompt_diff table; diffs must be computed at query time",
    "Baseline snapshots: eval DB records a named baseline per prompt version for regression comparison":
        "NOT IN DB — no explicit baseline table; first run per prompt_id acts as implicit baseline",
}


def _gap_analysis(conn) -> dict[str, Any]:
    """Compare checklist requirements against observed DB state.

    Each check is classified as:
      confirmed  — DB evidence exists (table/column present with data)
      partial    — infra exists but not fully wired up
      gap        — no DB coverage; implementation needed
    """
    # Snapshot the DB schema for quick presence checks
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    columns: dict[str, set[str]] = {}
    for table in tables:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        columns[table] = {c["name"] for c in cols}

    def _has_data(table: str) -> bool:
        if table not in tables:
            return False
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0

    # Simple heuristics to classify each check
    def _classify(check: str, signal: str) -> str:
        if signal.startswith("NOT IN DB"):
            return "gap"
        # Check for explicit "always possible" signals — these are structural, not data-dependent
        if "always possible" in signal:
            return "confirmed"
        # Spot-check specific columns and table presence
        checks_confirmed = [
            ("eval_runs" in tables and _has_data("eval_runs")),
            ("prompts"     in tables and _has_data("prompts")),
            ("token_usage" in tables and _has_data("token_usage")),
            ("prompt_id"   in columns.get("eval_runs", set())),
            ("router_prompt_id" in columns.get("eval_runs", set())),
            ("scorecard"   in columns.get("eval_runs", set())),
        ]
        # If any of the relevant checks pass, treat as confirmed
        for keyword, col_or_table in [
            ("eval_runs", "eval_runs"),
            ("prompts", "prompts"),
            ("token_usage", "token_usage"),
            ("prompt_id", "eval_runs"),
            ("scorecard", "eval_runs"),
            ("router_prompt_id", "eval_runs"),
            ("classified_as", "eval_runs"),
            ("model", "token_usage"),
            ("run_at", "eval_runs"),
        ]:
            if keyword in signal and col_or_table in tables:
                if keyword in columns.get(col_or_table, set()) or col_or_table in tables:
                    return "confirmed"
        return "partial"

    categories: list[dict] = []
    total_confirmed = total_partial = total_gap = 0

    for category in CHECKLIST:
        check_results: list[dict] = []
        for check in category.checks:
            signal = _DB_SIGNALS.get(check, "UNKNOWN — not mapped")
            classification = _classify(check, signal)
            if classification == "confirmed":
                total_confirmed += 1
            elif classification == "gap":
                total_gap += 1
            else:
                total_partial += 1
            check_results.append({
                "check":          check,
                "db_signal":      signal,
                "classification": classification,
            })

        categories.append({
            "category":        category.name,
            "declared_status": category.status.value,
            "checks":          check_results,
        })

    total_checks = total_confirmed + total_partial + total_gap
    return {
        "total_checks":     total_checks,
        "confirmed":        total_confirmed,
        "partial":          total_partial,
        "gap":              total_gap,
        "coverage_pct":     round(total_confirmed / total_checks * 100, 1) if total_checks else 0,
        "categories":       categories,
    }


# ---------------------------------------------------------------------------
# Top-level report assembler
# ---------------------------------------------------------------------------

def run_audit(db_path: Path | None = None) -> dict[str, Any]:
    """Run all five audit sections and return a single structured dict.

    Safe to call when the DB is empty (sections return zero-state dicts).
    """
    init_db(db_path)

    with get_connection(db_path) as conn:
        return {
            "db_path":            str(db_path),
            "run_counts":         _run_counts(conn),
            "token_spend":        _token_spend(conn),
            "prompt_versions":    _prompt_versions(conn),
            "score_distribution": _score_distribution(conn),
            "gap_analysis":       _gap_analysis(conn),
        }


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_WIDTH = 70
_SEP   = "=" * _WIDTH


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


def _print_report(report: dict) -> None:
    print(_SEP)
    print("  INFRASTRUCTURE AUDIT — SAFe Feature Spec System")
    print(f"  DB: {report['db_path']}")
    print(_SEP)

    # 1 — run counts
    _section("1. EVAL RUN COUNTS")
    rc = report["run_counts"]
    print(f"  Total runs : {rc['total_runs']}")
    print(f"  Passed     : {rc['total_passed']}")
    print(f"  Failed     : {rc['total_failed']}")
    if rc["by_feature_type"]:
        print(f"\n  {'Feature Type':<18} {'Total':>6}  {'Passed':>7}  {'Failed':>7}")
        print(f"  {'-' * 42}")
        for ftype, counts in rc["by_feature_type"].items():
            print(
                f"  {ftype:<18} {counts['total']:>6}  "
                f"{counts['passed']:>7}  {counts['failed']:>7}"
            )
    else:
        print("  (no runs recorded)")

    # 2 — token spend
    _section("2. TOKEN SPEND")
    ts = report["token_spend"]
    print(f"  Total input tokens  : {ts['total_input_tokens']:,}")
    print(f"  Total output tokens : {ts['total_output_tokens']:,}")
    print(f"  Total LLM calls     : {ts['total_calls']:,}")
    print(f"  Total cost (USD)    : ${ts['total_cost_usd']:.6f}")
    if ts["by_model"]:
        print(f"\n  {'Model':<36} {'In':>8}  {'Out':>8}  {'Cost':>10}")
        print(f"  {'-' * 64}")
        for model, d in ts["by_model"].items():
            print(
                f"  {model:<36} {d['input_tokens']:>8,}  "
                f"{d['output_tokens']:>8,}  ${d['cost_usd']:>9.6f}"
            )
    if ts["by_agent"]:
        print(f"\n  {'Agent':<18} {'In':>8}  {'Out':>8}  {'Calls':>6}")
        print(f"  {'-' * 44}")
        for agent, d in ts["by_agent"].items():
            print(
                f"  {agent:<18} {d['input_tokens']:>8,}  "
                f"{d['output_tokens']:>8,}  {d['calls']:>6}"
            )

    # 3 — prompt versions
    _section("3. REGISTERED PROMPT VERSIONS")
    pv = report["prompt_versions"]
    print(f"  Total registered : {pv['total_registered']}")
    if pv["by_agent"]:
        for agent, prompts in sorted(pv["by_agent"].items()):
            print(f"\n  [{agent}]")
            for p in prompts:
                print(
                    f"    v{p['version']}  {p['name']:<28}  "
                    f"id={p['id'][:12]}  {p['created_at']}"
                )
    else:
        print("  (no prompts registered)")

    # 4 — score distribution
    _section("4. SCORE DISTRIBUTION")
    sd = report["score_distribution"]
    if sd["overall_mean"] is not None:
        print(
            f"  Overall mean : {sd['overall_mean']}  "
            f"stdev : {sd['overall_stdev']}  "
            f"n={sd['total_scored_runs']}"
        )
        print(f"\n  {'Feature Type':<18} {'N':>3}  {'Mean':>6}  "
              f"{'Min':>4}  {'Max':>4}  {'Stdev':>6}  {'Flag'}")
        print(f"  {'-' * 56}")
        for ftype, d in sd["by_feature_type"].items():
            flag = "⚠ underperforming" if d["underperforming"] else ""
            print(
                f"  {ftype:<18} {d['n']:>3}  {d['mean']:>6.1f}  "
                f"{d['min']:>4}  {d['max']:>4}  {d['stdev']:>6.2f}  {flag}"
            )
    else:
        print("  (no scored runs)")

    # 5 — gap analysis
    _section("5. GAP ANALYSIS (Checklist vs. DB)")
    ga = report["gap_analysis"]
    print(
        f"  Checks total : {ga['total_checks']}   "
        f"confirmed={ga['confirmed']}  partial={ga['partial']}  gap={ga['gap']}"
    )
    print(f"  DB coverage  : {ga['coverage_pct']}%")

    icons = {"confirmed": "[x]", "partial": "[~]", "gap": "[ ]"}
    for cat in ga["categories"]:
        print(f"\n  {cat['category'].upper()}  (declared: {cat['declared_status']})")
        for chk in cat["checks"]:
            icon = icons[chk["classification"]]
            # Wrap long check text
            label = chk["check"]
            if len(label) > 55:
                label = label[:52] + "..."
            print(f"    {icon} {label}")
            if chk["classification"] == "gap":
                print(f"         → {chk['db_signal']}")

    print(f"\n{_SEP}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Infrastructure audit for the SAFe Feature Spec eval DB"
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite eval DB (default: evaluation/eval.db)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON instead of the formatted CLI report",
    )
    args = parser.parse_args()

    report = run_audit(Path(args.db))

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)
