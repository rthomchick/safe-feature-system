"""
evaluation/responsible_ai_template.py

Reusable responsible AI governance template — copy and configure for any AI tool
in the portfolio.

Design intent
─────────────
Different AI tools have different risk profiles:
  • A generative spec writer needs grounding checks (can hallucinate facts).
  • A calculator / ROI tool doesn't — it should be deterministic.
  • A query assistant needs fairness across topic categories, not feature types.

ResponsibleAIConfig captures that per-tool configuration. assess_tool() runs
the relevant checks and returns a unified health report, so every tool in the
portfolio can answer "am I healthy?" with one function call.

Pre-built configs
─────────────────
  SAFE_FEATURE_SYSTEM_CONFIG    — the SAFe Feature Spec pipeline (all checks)
  KNOWLEDGE_ASSISTANT_CONFIG    — RAG / search tool (grounding + fairness by topic)
  ROI_ANALYZER_CONFIG           — calculation tool (no grounding, cost + audit only)
  FEATURE_SPEC_GENERATOR_CONFIG — lightweight subset for a standalone generator

CLI
───
  python -m evaluation.responsible_ai_template --tool safe-feature-system
  python -m evaluation.responsible_ai_template --tool knowledge-assistant
  python -m evaluation.responsible_ai_template --tool roi-analyzer
  python -m evaluation.responsible_ai_template --tool feature-spec-generator
  python -m evaluation.responsible_ai_template          # lists available tools
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.eval_db import DEFAULT_DB_PATH, get_connection, init_db


# ---------------------------------------------------------------------------
# ResponsibleAIConfig
# ---------------------------------------------------------------------------

@dataclass
class ResponsibleAIConfig:
    """
    Governance configuration for a single AI tool.

    Pass to assess_tool() to get a health report.  Only enabled checks are run.

    Attributes:
        tool_name: Human-readable name, used in reports and CLI selection.
        checks:    Dict of check-name → config dict.  Required keys per check:

          fairness:
            enabled           bool   — run cross-category bias detection
            categories        list   — category labels expected in the DB
                                       (feature_type for SAFe, topic for RAG, etc.)
            threshold         float  — max allowable score gap between categories (pts)

          reliability:
            enabled           bool   — run score variance and golden-set coverage checks
            max_variance_pct  float  — max allowable coefficient of variation (%)
            min_golden_set_size int  — minimum number of distinct golden-set cases

          grounding:
            enabled           bool   — enable for generative tools, disable for calculators
            min_grounded_pct  float  — minimum % of spec claims rated GROUNDED

          cost:
            enabled           bool   — enforce spending limits
            per_run_max       float  — USD ceiling per single pipeline run
            daily_max         float  — USD ceiling for all runs in a calendar day (UTC)

          audit:
            enabled           bool   — check whether decision traces are being recorded
            log_all_llm_calls bool   — require every LLM call to appear in token_usage
            retention_days    int    — minimum days of audit trail to retain
    """

    tool_name: str
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get_active_checks(self) -> dict[str, dict[str, Any]]:
        """Return only the check entries that are enabled."""
        return {
            name: cfg
            for name, cfg in self.checks.items()
            if cfg.get("enabled", False)
        }


# ---------------------------------------------------------------------------
# Pre-built configs
# ---------------------------------------------------------------------------

SAFE_FEATURE_SYSTEM_CONFIG = ResponsibleAIConfig(
    tool_name="safe-feature-system",
    checks={
        "fairness": {
            "enabled":    True,
            "categories": ["CAPABILITY", "WEBPAGE", "EXPERIENCE"],
            "threshold":  10.0,   # flag if best-vs-worst gap exceeds 10 pts
        },
        "reliability": {
            "enabled":            True,
            "max_variance_pct":   25.0,   # CV > 25% suggests inconsistent output
            "min_golden_set_size": 6,     # 3 types × bare + boosted
        },
        "grounding": {
            "enabled":          True,
            "min_grounded_pct": 90.0,    # ≥90% of spec claims must be grounded
        },
        "cost": {
            "enabled":     True,
            "per_run_max": 0.50,
            "daily_max":   5.00,
        },
        "audit": {
            "enabled":           True,
            "log_all_llm_calls": True,
            "retention_days":    90,
        },
    },
)

KNOWLEDGE_ASSISTANT_CONFIG = ResponsibleAIConfig(
    tool_name="knowledge-assistant",
    checks={
        "fairness": {
            "enabled":    True,
            # For a RAG/search tool, categories are query topic buckets
            "categories": ["product", "pricing", "technical", "support"],
            "threshold":  8.0,   # tighter — retrieval should be topic-neutral
        },
        "reliability": {
            "enabled":            True,
            "max_variance_pct":   20.0,
            "min_golden_set_size": 10,   # broader query coverage expected
        },
        "grounding": {
            "enabled":          True,
            "min_grounded_pct": 95.0,   # higher bar — answers must cite sources
        },
        "cost": {
            "enabled":     True,
            "per_run_max": 0.10,   # RAG calls are cheaper than full spec generation
            "daily_max":   2.00,
        },
        "audit": {
            "enabled":           True,
            "log_all_llm_calls": True,
            "retention_days":    30,
        },
    },
)

ROI_ANALYZER_CONFIG = ResponsibleAIConfig(
    tool_name="roi-analyzer",
    checks={
        "fairness": {
            "enabled":    True,
            "categories": ["cost_reduction", "revenue_growth", "risk_mitigation"],
            "threshold":  15.0,   # wider — ROI scenarios naturally vary by type
        },
        "reliability": {
            "enabled":            True,
            "max_variance_pct":   10.0,   # calculations should be highly consistent
            "min_golden_set_size": 4,
        },
        "grounding": {
            # Disabled: the ROI analyzer calculates from structured inputs.
            # It doesn't generate free-text claims that could be hallucinated.
            "enabled": False,
            "min_grounded_pct": 0.0,
        },
        "cost": {
            "enabled":     True,
            "per_run_max": 0.05,   # lightweight — mostly structured output
            "daily_max":   1.00,
        },
        "audit": {
            "enabled":           True,
            "log_all_llm_calls": True,
            "retention_days":    180,   # longer — financial outputs need audit history
        },
    },
)

FEATURE_SPEC_GENERATOR_CONFIG = ResponsibleAIConfig(
    tool_name="feature-spec-generator",
    checks={
        "fairness": {
            # Lightweight: only CAPABILITY features in this standalone generator
            "enabled":    True,
            "categories": ["CAPABILITY"],
            "threshold":  10.0,
        },
        "reliability": {
            "enabled":            True,
            "max_variance_pct":   30.0,   # more tolerance — early-stage tool
            "min_golden_set_size": 3,
        },
        "grounding": {
            "enabled":          True,
            "min_grounded_pct": 85.0,   # slightly lower bar for standalone tool
        },
        "cost": {
            "enabled":     False,   # not yet instrumented for cost tracking
            "per_run_max": 0.50,
            "daily_max":   5.00,
        },
        "audit": {
            "enabled":           True,
            "log_all_llm_calls": False,   # audit trail enabled, LLM-level logging optional
            "retention_days":    30,
        },
    },
)

# Registry — maps CLI --tool values to configs
_TOOL_REGISTRY: dict[str, ResponsibleAIConfig] = {
    cfg.tool_name: cfg
    for cfg in [
        SAFE_FEATURE_SYSTEM_CONFIG,
        KNOWLEDGE_ASSISTANT_CONFIG,
        ROI_ANALYZER_CONFIG,
        FEATURE_SPEC_GENERATOR_CONFIG,
    ]
}


# ---------------------------------------------------------------------------
# assess_tool — the single "is my tool healthy?" entry point
# ---------------------------------------------------------------------------

def assess_tool(
    config: ResponsibleAIConfig,
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """
    Run all active checks from config against the eval DB and return a health report.

    Returns:
        {
            "tool":        str,
            "assessed_at": ISO-8601 timestamp,
            "db_path":     str,
            "overall":     "HEALTHY" | "DEGRADED" | "UNHEALTHY",
            "checks_run":  [str],          # names of enabled checks
            "checks_skipped": [str],       # names of disabled checks
            "results": {
                "fairness":    {...},
                "reliability": {...},
                "grounding":   {...},
                "cost":        {...},
                "audit":       {...},
            },
            "findings": [str],             # actionable issues across all checks
            "warnings": [str],             # non-blocking concerns
        }
    """
    assessed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    active      = config.get_active_checks()
    skipped     = [k for k in config.checks if k not in active]

    report: dict[str, Any] = {
        "tool":           config.tool_name,
        "assessed_at":    assessed_at,
        "db_path":        str(db_path),
        "overall":        "HEALTHY",
        "checks_run":     list(active.keys()),
        "checks_skipped": skipped,
        "results":        {},
        "findings":       [],
        "warnings":       [],
    }

    # Initialise DB if needed (no-op if tables already exist)
    try:
        init_db(db_path)
    except Exception as exc:
        report["overall"]  = "UNHEALTHY"
        report["findings"].append(f"DB init failed: {exc}")
        return report

    db_exists = db_path.exists()

    if "fairness" in active:
        result = _check_fairness(active["fairness"], db_path, db_exists)
        report["results"]["fairness"] = result
        _merge_findings(report, result)

    if "reliability" in active:
        result = _check_reliability(active["reliability"], db_path, db_exists)
        report["results"]["reliability"] = result
        _merge_findings(report, result)

    if "grounding" in active:
        result = _check_grounding(active["grounding"], db_path, db_exists)
        report["results"]["grounding"] = result
        _merge_findings(report, result)

    if "cost" in active:
        result = _check_cost(active["cost"], db_path, db_exists)
        report["results"]["cost"] = result
        _merge_findings(report, result)

    if "audit" in active:
        result = _check_audit(active["audit"], db_path, db_exists)
        report["results"]["audit"] = result
        _merge_findings(report, result)

    # Roll up overall status
    if report["findings"]:
        report["overall"] = "UNHEALTHY"
    elif report["warnings"]:
        report["overall"] = "DEGRADED"

    return report


def _merge_findings(report: dict, result: dict) -> None:
    report["findings"].extend(result.get("findings", []))
    report["warnings"].extend(result.get("warnings", []))


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------

def _check_fairness(
    cfg: dict,
    db_path: Path,
    db_exists: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status":   "SKIP",
        "findings": [],
        "warnings": [],
    }
    if not db_exists:
        result["warnings"].append("fairness: DB not found — no data to analyse")
        return result

    try:
        from evaluation.bias_detector import run_bias_report
        report = run_bias_report(db_path, threshold=cfg["threshold"])
    except Exception as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"fairness: error running bias detector — {exc}")
        return result

    bias = report.get("bias", {})
    result["bias_detected"]    = bias.get("bias_detected", False)
    result["max_gap"]          = bias.get("max_gap", 0.0)
    result["threshold"]        = cfg["threshold"]
    result["low_sample"]       = bias.get("low_sample_warning", False)
    result["category_stats"]   = bias.get("category_stats", {})

    if bias.get("bias_detected"):
        gap = bias.get("max_gap", 0)
        worst = bias.get("worst_category", "?")
        result["findings"].append(
            f"fairness: score gap {gap:.1f} pts exceeds {cfg['threshold']:.0f}-pt threshold "
            f"(worst category: {worst})"
        )
    elif bias.get("low_sample_warning"):
        result["warnings"].append(
            f"fairness: gap is {bias.get('max_gap', 0):.1f} pts but sample size is too small "
            "for reliable conclusions — run more golden-set evaluations"
        )

    # Check expected categories are present
    observed = set(bias.get("category_stats", {}).keys())
    expected = set(cfg.get("categories", []))
    missing_cats = expected - observed
    if missing_cats:
        result["warnings"].append(
            f"fairness: no eval runs found for categories: {sorted(missing_cats)}"
        )

    result["status"] = "FAIL" if result["findings"] else "PASS"
    return result


def _check_reliability(
    cfg: dict,
    db_path: Path,
    db_exists: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status":   "SKIP",
        "findings": [],
        "warnings": [],
    }
    if not db_exists:
        result["warnings"].append("reliability: DB not found — no data to analyse")
        return result

    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(final_score, original_score) AS score,
                       golden_set_id
                FROM   eval_runs
                WHERE  COALESCE(final_score, original_score) IS NOT NULL
                """
            ).fetchall()
    except Exception as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"reliability: DB query failed — {exc}")
        return result

    scores = [float(r["score"]) for r in rows]
    golden_set_ids = {r["golden_set_id"] for r in rows}

    result["total_runs"]      = len(scores)
    result["golden_set_size"] = len(golden_set_ids)

    if not scores:
        result["warnings"].append("reliability: no scored eval runs in DB")
        result["status"] = "SKIP"
        return result

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stdev = math.sqrt(variance)
    cv_pct = (stdev / mean * 100) if mean > 0 else 0.0

    result["mean"]   = round(mean, 2)
    result["stdev"]  = round(stdev, 2)
    result["cv_pct"] = round(cv_pct, 2)

    max_cv = cfg["max_variance_pct"]
    min_gs = cfg["min_golden_set_size"]

    if cv_pct > max_cv:
        result["findings"].append(
            f"reliability: score variance CV={cv_pct:.1f}% exceeds {max_cv:.0f}% threshold "
            f"(mean={mean:.1f}, stdev={stdev:.1f}) — output quality is inconsistent"
        )

    if len(golden_set_ids) < min_gs:
        result["findings"].append(
            f"reliability: only {len(golden_set_ids)} distinct golden-set cases "
            f"(need ≥ {min_gs}) — expand the golden set for meaningful eval coverage"
        )

    result["status"] = "FAIL" if result["findings"] else "PASS"
    return result


def _check_grounding(
    cfg: dict,
    db_path: Path,
    db_exists: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status":   "SKIP",
        "findings": [],
        "warnings": [],
    }
    if not db_exists:
        result["warnings"].append("grounding: DB not found — no data to analyse")
        return result

    # Pull grounding results from the audit trail (event_type = GROUND_CHECK)
    try:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                """
                SELECT details_json
                FROM   audit_trail
                WHERE  event_type = 'GROUND_CHECK'
                ORDER  BY timestamp DESC
                LIMIT  50
                """
            ).fetchall()
    except Exception as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"grounding: DB query failed — {exc}")
        return result

    if not rows:
        result["warnings"].append(
            "grounding: no GROUND_CHECK events found in audit trail — "
            "run evaluation.grounding_checker to populate"
        )
        result["status"] = "SKIP"
        return result

    grounded_pcts: list[float] = []
    fails = 0
    for r in rows:
        try:
            d = json.loads(r["details_json"])
            pct = float(d.get("grounded_pct", 0))
            grounded_pcts.append(pct)
            if d.get("verdict") == "FAIL":
                fails += 1
        except (json.JSONDecodeError, KeyError, ValueError):
            continue

    if not grounded_pcts:
        result["warnings"].append(
            "grounding: GROUND_CHECK events present but no grounded_pct values found"
        )
        result["status"] = "SKIP"
        return result

    mean_grounded = sum(grounded_pcts) / len(grounded_pcts)
    min_grounded  = min(grounded_pcts)
    min_required  = cfg["min_grounded_pct"]

    result["checks_run"]    = len(grounded_pcts)
    result["mean_grounded"] = round(mean_grounded, 1)
    result["min_grounded"]  = round(min_grounded, 1)
    result["fail_count"]    = fails

    if mean_grounded < min_required:
        result["findings"].append(
            f"grounding: mean grounded={mean_grounded:.1f}% is below {min_required:.0f}% threshold "
            f"({fails} of {len(grounded_pcts)} checks returned FAIL)"
        )
    elif min_grounded < min_required - 10:
        result["warnings"].append(
            f"grounding: mean {mean_grounded:.1f}% is acceptable but worst case "
            f"min={min_grounded:.1f}% — some outputs are poorly grounded"
        )

    result["status"] = "FAIL" if result["findings"] else "PASS"
    return result


def _check_cost(
    cfg: dict,
    db_path: Path,
    db_exists: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status":   "SKIP",
        "findings": [],
        "warnings": [],
    }
    if not db_exists:
        result["warnings"].append("cost: DB not found — cannot check spend")
        return result

    try:
        from evaluation.cost_guardrails import get_daily_spend, COST_LIMITS
    except ImportError as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"cost: import error — {exc}")
        return result

    try:
        daily_spend = get_daily_spend(db_path)
    except Exception as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"cost: failed to query daily spend — {exc}")
        return result

    per_run_max = cfg["per_run_max"]
    daily_max   = cfg["daily_max"]

    result["daily_spend_usd"] = round(daily_spend, 4)
    result["daily_max_usd"]   = daily_max

    # Check recent run costs against per_run_max
    try:
        with get_connection(db_path) as conn:
            recent_runs = conn.execute(
                """
                SELECT er.id, SUM(tu.input_tokens * 0.000003 + tu.output_tokens * 0.000015) AS cost_usd
                FROM   eval_runs er
                JOIN   token_usage tu ON tu.run_id = er.id
                WHERE  er.run_at >= date('now', '-1 day')
                GROUP  BY er.id
                ORDER  BY er.run_at DESC
                LIMIT  20
                """
            ).fetchall()
    except Exception:
        recent_runs = []

    over_budget_runs = [
        r for r in recent_runs
        if r["cost_usd"] is not None and float(r["cost_usd"]) > per_run_max
    ]

    result["recent_runs_checked"] = len(recent_runs)
    result["runs_over_budget"]    = len(over_budget_runs)

    if daily_spend > daily_max:
        result["findings"].append(
            f"cost: daily spend ${daily_spend:.2f} exceeds ${daily_max:.2f} limit"
        )
    elif daily_spend >= daily_max * 0.80:
        result["warnings"].append(
            f"cost: daily spend ${daily_spend:.2f} is ≥80% of ${daily_max:.2f} daily limit"
        )

    if over_budget_runs:
        result["warnings"].append(
            f"cost: {len(over_budget_runs)} recent run(s) exceeded the "
            f"${per_run_max:.2f}/run limit"
        )

    result["status"] = "FAIL" if result["findings"] else "PASS"
    return result


def _check_audit(
    cfg: dict,
    db_path: Path,
    db_exists: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status":   "SKIP",
        "findings": [],
        "warnings": [],
    }
    if not db_exists:
        result["findings"].append(
            "audit: DB not found — no audit trail is being recorded"
        )
        result["status"] = "FAIL"
        return result

    try:
        with get_connection(db_path) as conn:
            trail_count = conn.execute(
                "SELECT COUNT(*) AS n FROM audit_trail"
            ).fetchone()["n"]

            token_count = conn.execute(
                "SELECT COUNT(*) AS n FROM token_usage"
            ).fetchone()["n"]

            run_count = conn.execute(
                "SELECT COUNT(*) AS n FROM eval_runs"
            ).fetchone()["n"]

            oldest_run = conn.execute(
                "SELECT MIN(run_at) AS oldest FROM eval_runs"
            ).fetchone()["oldest"]
    except Exception as exc:
        result["status"] = "ERROR"
        result["findings"].append(f"audit: DB query failed — {exc}")
        return result

    result["audit_trail_events"] = trail_count
    result["token_usage_rows"]   = token_count
    result["eval_run_count"]     = run_count

    # Check audit trail coverage
    if trail_count == 0:
        result["findings"].append(
            "audit: audit_trail table is empty — decision traces are not being recorded"
        )

    # Check LLM call logging if required
    if cfg.get("log_all_llm_calls") and run_count > 0:
        if token_count == 0:
            result["findings"].append(
                "audit: token_usage table is empty — LLM calls are not being logged"
            )
        elif token_count < run_count:
            result["warnings"].append(
                f"audit: {token_count} token_usage rows for {run_count} runs — "
                "some runs may have unlogged LLM calls"
            )

    # Check retention
    if oldest_run:
        try:
            from datetime import datetime
            oldest_dt = datetime.fromisoformat(oldest_run.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - oldest_dt.replace(tzinfo=timezone.utc)).days
            result["oldest_run_age_days"] = age_days
            retention = cfg.get("retention_days", 30)
            if age_days < retention:
                result["warnings"].append(
                    f"audit: oldest run is {age_days} days old — "
                    f"data retention target is {retention} days (still accumulating)"
                )
        except (ValueError, TypeError):
            pass

    result["status"] = "FAIL" if result["findings"] else "PASS"
    return result


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_W = 72
_STATUS_ICONS = {"PASS": "✓", "FAIL": "✗", "SKIP": "○", "ERROR": "!"}
_OVERALL_ICONS = {"HEALTHY": "✓", "DEGRADED": "~", "UNHEALTHY": "✗"}


def _print_report(report: dict) -> None:
    overall      = report["overall"]
    overall_icon = _OVERALL_ICONS.get(overall, "?")

    print("=" * _W)
    print(f"  RESPONSIBLE AI ASSESSMENT — {report['tool']}")
    print(f"  {report['assessed_at']}   DB: {report['db_path']}")
    print("=" * _W)
    print(f"\n  Overall: {overall_icon} {overall}\n")

    for check_name in report["checks_run"]:
        res    = report["results"].get(check_name, {})
        status = res.get("status", "SKIP")
        icon   = _STATUS_ICONS.get(status, "?")
        print(f"  {icon} {check_name.upper():<14}  {status}")

        # Print key metrics per check
        if check_name == "fairness" and "max_gap" in res:
            print(f"      max category gap: {res['max_gap']:.1f} pts  "
                  f"(threshold: {res.get('threshold', '?')} pts)")
        elif check_name == "reliability" and "cv_pct" in res:
            print(f"      CV: {res['cv_pct']:.1f}%   "
                  f"mean: {res.get('mean', 0):.1f}   "
                  f"golden set: {res.get('golden_set_size', 0)} cases")
        elif check_name == "grounding" and "mean_grounded" in res:
            print(f"      mean grounded: {res['mean_grounded']:.1f}%  "
                  f"({res.get('checks_run', 0)} checks,  "
                  f"{res.get('fail_count', 0)} failures)")
        elif check_name == "cost" and "daily_spend_usd" in res:
            print(f"      daily spend: ${res['daily_spend_usd']:.4f} / "
                  f"${res.get('daily_max_usd', 0):.2f} limit")
        elif check_name == "audit" and "audit_trail_events" in res:
            print(f"      audit events: {res['audit_trail_events']}   "
                  f"token rows: {res.get('token_usage_rows', 0)}   "
                  f"runs: {res.get('eval_run_count', 0)}")

    if report["checks_skipped"]:
        print(f"\n  Skipped: {', '.join(report['checks_skipped'])}")

    if report["findings"]:
        print(f"\n  Issues ({len(report['findings'])}):")
        for f in report["findings"]:
            print(f"    ✗ {f}")

    if report["warnings"]:
        print(f"\n  Warnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"    ~ {w}")

    if not report["findings"] and not report["warnings"]:
        print("\n  No issues or warnings found.")

    print("=" * _W)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Responsible AI assessment for a configured tool"
    )
    parser.add_argument(
        "--tool",
        metavar="TOOL_NAME",
        choices=list(_TOOL_REGISTRY.keys()),
        help="Tool to assess. Choices: " + ", ".join(_TOOL_REGISTRY.keys()),
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to eval SQLite DB",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted report",
    )
    args = parser.parse_args()

    if not args.tool:
        print("Available tools:")
        for name, cfg in _TOOL_REGISTRY.items():
            active = cfg.get_active_checks()
            print(f"  {name:<30}  checks: {', '.join(active.keys())}")
        sys.exit(0)

    config  = _TOOL_REGISTRY[args.tool]
    db_path = Path(args.db)

    report = assess_tool(config, db_path)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)

    sys.exit(0 if report["overall"] == "HEALTHY" else 1)
