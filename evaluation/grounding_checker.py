"""
evaluation/grounding_checker.py

LLM-as-judge grounding checker for the SAFe Feature Spec pipeline.

Verifies that generated specs are grounded in PM-provided inputs. Every claim
in the spec is classified as:

  GROUNDED      — explicitly supported by PM inputs (not counted as unsupported)
  EXTRAPOLATION — reasonable inference; no direct basis but not contradictory (acceptable)
  INVENTION     — no basis in inputs whatsoever (problematic)
  CONTRADICTION — conflicts with something the PM explicitly stated (critical)

Verdict thresholds:
  PASS  — grounded_percentage >= 90 AND no CONTRADICTION
  WARN  — grounded_percentage >= 75 AND no CONTRADICTION (only EXTRAPOLATIONs)
  FAIL  — grounded_percentage <  75 OR any CONTRADICTION

Data sourcing note:
  eval_runs stores the reviewer scorecard but NOT the generated spec text or the
  original PM inputs (section_answers). For the golden set runner we re-generate
  specs live from section_answers — the same path eval_runner.py uses. This keeps
  the grounding checker honest: it judges the live output, not a cached copy.

CLI:
  python -m evaluation.grounding_checker                  # run all golden set cases
  python -m evaluation.grounding_checker --case cap_001_bare  # single case, verbose
  python -m evaluation.grounding_checker --run-id <uuid>  # check a past run's case
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

import anthropic
import streamlit as st


def _get_api_key(key_name: str) -> str:
    """Retrieve API key from Streamlit secrets or environment; raise on missing."""
    try:
        return st.secrets[key_name]
    except Exception:
        pass
    value = os.environ.get(key_name)
    if not value:
        raise RuntimeError(
            f"Missing required API key: {key_name}. "
            f"Set it in .streamlit/secrets.toml or as an environment variable."
        )
    return value


_api_key = _get_api_key("ANTHROPIC_API_KEY")

from evaluation.eval_db import DEFAULT_DB_PATH, get_connection, init_db
from evaluation.golden_set import GOLDEN_SET
from evaluation.token_tracker import TokenTracker, llm_call
from evaluation.cost_guardrails import CostGuard, llm_call_guarded

_client = anthropic.Anthropic(api_key=_api_key)

_GROUNDING_MODEL   = "claude-sonnet-4-5-20250929"
_GROUNDING_AGENT   = "grounding_check"
_MAX_TOKENS        = 4096
_TEMPERATURE       = 0.0

# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

PASS_THRESHOLD = 90   # grounded_percentage >= 90 AND no CONTRADICTION → PASS
WARN_THRESHOLD = 75   # grounded_percentage >= 75 AND no CONTRADICTION → WARN
                      # grounded_percentage <  75 OR any CONTRADICTION  → FAIL

# ---------------------------------------------------------------------------
# Grounding judge system prompt
# ---------------------------------------------------------------------------

GROUNDING_CHECK_PROMPT = """\
You are a grounding auditor for AI-generated SAFe Feature specifications.

Your job is to determine whether every claim in a generated spec is traceable to the \
PM-provided inputs. You are NOT evaluating quality, completeness, or writing style — \
only factual traceability.

## Inputs you will receive

1. PM_INPUTS — the structured interview answers the PM provided, organized by section.
2. BOOST_INPUTS — optional supplementary context the PM added (may be empty).
3. GENERATED_SPEC — the full SAFe Feature specification produced by the AI generator.

## Classification rules

For every substantive claim in GENERATED_SPEC, classify it as one of:

GROUNDED
  The claim is explicitly stated, clearly implied, or directly derivable from PM_INPUTS \
or BOOST_INPUTS. Do NOT list GROUNDED claims — only report unsupported ones.

EXTRAPOLATION
  The claim is a reasonable professional inference from the inputs. The PM did not say it, \
but a skilled PM would expect it to appear. It does not contradict anything stated.
  Examples: adding standard SAFe boilerplate, inferring a standard integration step from \
a named system, filling a [NEEDS INPUT] placeholder with a sensible default.
  Verdict impact: acceptable — does not trigger FAIL.

INVENTION
  The claim introduces specific facts (metrics, system names, team names, timelines, \
thresholds, costs, features) with no basis in the inputs and no reasonable inference path.
  Examples: a specific percentage target not in the inputs, a named third-party system \
not mentioned by the PM, a feature capability the PM never described.
  Verdict impact: problematic — each INVENTION lowers the grounded_percentage.

CONTRADICTION
  The claim directly conflicts with something the PM stated.
  Examples: spec says "no user-facing UI" when PM described a UI component; spec says \
"batch processing" when PM requested real-time; spec inverts a priority the PM set.
  Verdict impact: critical — any CONTRADICTION forces verdict to FAIL.

## Scoring

grounded_percentage = (total_claims - EXTRAPOLATION_count - INVENTION_count - CONTRADICTION_count) \
/ total_claims * 100

Round to one decimal place. Count each distinct claim as one unit; do not double-count \
claims that appear in multiple sections.

## Verdict logic

PASS  if grounded_percentage >= 90 AND CONTRADICTION_count == 0
WARN  if grounded_percentage >= 75 AND CONTRADICTION_count == 0
FAIL  if grounded_percentage <  75 OR  CONTRADICTION_count  > 0

## Output format

Return ONLY valid JSON. No preamble, no explanation, no markdown code fences.

{
  "grounded_percentage": <float, one decimal place>,
  "total_claims_evaluated": <integer>,
  "verdict": "PASS" | "WARN" | "FAIL",
  "unsupported_claims": [
    {
      "claim": "<exact quote or close paraphrase of the claim from the spec>",
      "section": "<## heading the claim appears under>",
      "classification": "EXTRAPOLATION" | "INVENTION" | "CONTRADICTION",
      "explanation": "<one sentence: why this classification applies>"
    }
  ],
  "summary": "<two sentences: overall assessment and the most important finding>"
}

If there are no unsupported claims, return an empty array for unsupported_claims.\
"""

# ---------------------------------------------------------------------------
# Core check function
# ---------------------------------------------------------------------------

def check_grounding(
    pm_inputs: str,
    boost_inputs: str,
    generated_spec: str,
    tracker: TokenTracker | None = None,
    guard: CostGuard | None = None,
) -> dict[str, Any]:
    """Run the grounding judge on one generated spec.

    Args:
        pm_inputs:      PM's section_answers rendered as a single string
                        (section headers + answer text, same format the generator receives).
        boost_inputs:   Optional supplementary PM context (may be empty string).
        generated_spec: Full spec text returned by generate_feature_spec().
        tracker:        Optional TokenTracker for cost accounting.
        guard:          Optional CostGuard for spend enforcement.

    Returns:
        Structured grounding report:
        {
            "grounded_percentage":    float,
            "total_claims_evaluated": int,
            "verdict":                "PASS" | "WARN" | "FAIL",
            "unsupported_claims":     [...],
            "summary":                str,
            "parse_error":            str,   # present only if JSON parse failed
        }
    """
    boost_block = boost_inputs.strip() if boost_inputs else "(none provided)"

    user_message = f"""\
## PM_INPUTS

{pm_inputs.strip()}

## BOOST_INPUTS

{boost_block}

## GENERATED_SPEC

{generated_spec.strip()}
"""

    kwargs: dict[str, Any] = dict(
        model=_GROUNDING_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=_TEMPERATURE,
        system=GROUNDING_CHECK_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = llm_call_guarded(_client, tracker, guard, _GROUNDING_AGENT, **kwargs)

    # Strip accidental markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$",          "", cleaned,      flags=re.MULTILINE)

    try:
        report = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {
            "grounded_percentage":    0.0,
            "total_claims_evaluated": 0,
            "verdict":                "FAIL",
            "unsupported_claims":     [],
            "summary":                "JSON parse error — grounding check result is unavailable.",
            "parse_error":            f"{exc}: raw={raw[:200]}",
        }

    # Recompute verdict server-side so the thresholds are always authoritative
    report["verdict"] = _compute_verdict(
        report.get("grounded_percentage", 0.0),
        report.get("unsupported_claims", []),
    )

    return report


def _compute_verdict(grounded_pct: float, unsupported: list[dict]) -> str:
    has_contradiction = any(
        c.get("classification") == "CONTRADICTION" for c in unsupported
    )
    if has_contradiction or grounded_pct < WARN_THRESHOLD:
        return "FAIL"
    if grounded_pct < PASS_THRESHOLD:
        return "WARN"
    return "PASS"


# ---------------------------------------------------------------------------
# Golden set runner
# ---------------------------------------------------------------------------

def _section_answers_to_string(section_answers: dict[str, str]) -> str:
    """Render section_answers dict in the same format the generator receives."""
    parts = []
    for section_name, answer_text in section_answers.items():
        parts.append(f"## {section_name}\n{answer_text.strip()}")
    return "\n\n".join(parts)


def _get_golden_entry(case_id: str) -> dict | None:
    for entry in GOLDEN_SET:
        if entry["id"] == case_id:
            return entry
    return None


def run_grounding_on_golden_set(
    db_path: Path = DEFAULT_DB_PATH,
    case_filter: str | None = None,
) -> dict[str, Any]:
    """Re-generate specs from golden set inputs and run grounding on each.

    The generated spec is NOT read from the DB (eval_runs doesn't store it);
    it is regenerated live from section_answers. This is intentional — we
    judge the live generator output rather than a stale cached version.

    Args:
        db_path:      Path to the eval DB (used for context; not written to here).
        case_filter:  If set, only the golden set entry with this id is checked.

    Returns:
        {
            "cases": [
                {
                    "case_id":    str,
                    "name":       str,
                    "verdict":    "PASS"|"WARN"|"FAIL",
                    "grounded_percentage": float,
                    "invention_count":     int,
                    "extrapolation_count": int,
                    "contradiction_count": int,
                    "report":     dict,   # full grounding report
                }
            ],
            "total":         int,
            "pass_count":    int,
            "warn_count":    int,
            "fail_count":    int,
            "pass_rate_pct": float,
            "claim_type_totals": {"EXTRAPOLATION": int, "INVENTION": int, "CONTRADICTION": int},
        }
    """
    from agents.generator import generate_feature_spec
    from prompts import capabilities, experiences, webpages

    _PROMPT_MODULES = {
        "CAPABILITY": capabilities,
        "EXPERIENCE":  experiences,
        "WEBPAGE":     webpages,
    }

    entries = GOLDEN_SET
    if case_filter:
        entries = [e for e in GOLDEN_SET if e["id"] == case_filter]
        if not entries:
            ids = [e["id"] for e in GOLDEN_SET]
            raise ValueError(f"No golden set entry with id={case_filter!r}. Available: {ids}")

    case_results: list[dict] = []
    claim_type_totals: dict[str, int] = {"EXTRAPOLATION": 0, "INVENTION": 0, "CONTRADICTION": 0}

    for entry in entries:
        case_id      = entry["id"]
        feature_type = entry["feature_type"]
        section_answers = entry["section_answers"]

        print(f"\n  Checking {case_id} ({entry.get('name', '')}) …", flush=True)

        tracker = TokenTracker()

        # Step 1 — generate spec from PM inputs (same path as eval_runner)
        module = _PROMPT_MODULES[feature_type]
        try:
            spec = generate_feature_spec(
                feature_type=feature_type,
                preamble=module.PREAMBLE,
                section_answers=section_answers,
                tracker=tracker,
            )
        except Exception as exc:
            print(f"    [ERROR] generate_feature_spec failed: {exc}")
            case_results.append({
                "case_id": case_id,
                "name":    entry.get("name", case_id),
                "verdict": "FAIL",
                "grounded_percentage": 0.0,
                "invention_count":     0,
                "extrapolation_count": 0,
                "contradiction_count": 0,
                "error": str(exc),
                "report": {},
            })
            continue

        # Step 2 — run grounding check
        pm_inputs_str = _section_answers_to_string(section_answers)

        # boost_inputs: golden set doesn't carry a boost_inputs path field,
        # but boosted entries have richer section_answers already merged in.
        # We leave boost_inputs blank so the judge evaluates against the raw inputs.
        boost_inputs_str = ""

        try:
            report = check_grounding(
                pm_inputs=pm_inputs_str,
                boost_inputs=boost_inputs_str,
                generated_spec=spec,
                tracker=tracker,
            )
        except Exception as exc:
            print(f"    [ERROR] check_grounding failed: {exc}")
            case_results.append({
                "case_id": case_id,
                "name":    entry.get("name", case_id),
                "verdict": "FAIL",
                "grounded_percentage": 0.0,
                "invention_count":     0,
                "extrapolation_count": 0,
                "contradiction_count": 0,
                "error": str(exc),
                "report": {},
            })
            continue

        # Tally claim types
        by_type: dict[str, int] = {"EXTRAPOLATION": 0, "INVENTION": 0, "CONTRADICTION": 0}
        for claim in report.get("unsupported_claims", []):
            ctype = claim.get("classification", "")
            if ctype in by_type:
                by_type[ctype] += 1
                claim_type_totals[ctype] += 1

        verdict = report.get("verdict", "FAIL")
        pct     = report.get("grounded_percentage", 0.0)
        cost    = tracker.total_cost_usd()

        print(
            f"    verdict={verdict}  grounded={pct:.1f}%  "
            f"inventions={by_type['INVENTION']}  "
            f"contradictions={by_type['CONTRADICTION']}  "
            f"cost=${cost:.4f}"
        )

        case_results.append({
            "case_id":             case_id,
            "name":                entry.get("name", case_id),
            "verdict":             verdict,
            "grounded_percentage": pct,
            "invention_count":     by_type["INVENTION"],
            "extrapolation_count": by_type["EXTRAPOLATION"],
            "contradiction_count": by_type["CONTRADICTION"],
            "report":              report,
            "token_cost_usd":      cost,
        })

    pass_count = sum(1 for c in case_results if c["verdict"] == "PASS")
    warn_count = sum(1 for c in case_results if c["verdict"] == "WARN")
    fail_count = sum(1 for c in case_results if c["verdict"] == "FAIL")
    total      = len(case_results)

    return {
        "cases":            case_results,
        "total":            total,
        "pass_count":       pass_count,
        "warn_count":       warn_count,
        "fail_count":       fail_count,
        "pass_rate_pct":    round(pass_count / total * 100, 1) if total else 0.0,
        "claim_type_totals": claim_type_totals,
    }


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_WIDTH = 72
_VERDICT_ICONS = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
_CLASS_ICONS   = {
    "EXTRAPOLATION": "~",
    "INVENTION":     "!",
    "CONTRADICTION": "✗",
}


def _print_summary(result: dict[str, Any]) -> None:
    print("\n" + "=" * _WIDTH)
    print("  GROUNDING CHECK SUMMARY")
    print("=" * _WIDTH)
    print(
        f"  {'CASE ID':<24} {'TYPE':<5} {'VERDICT':<7}  {'GROUNDED':>8}  "
        f"{'EXT':>4}  {'INV':>4}  {'CON':>4}"
    )
    print(f"  {'-' * 62}")

    for c in result["cases"]:
        if "error" in c:
            print(f"  {c['case_id']:<24} ERROR: {c['error'][:30]}")
            continue
        icon = _VERDICT_ICONS.get(c["verdict"], "     ")
        print(
            f"  {c['case_id']:<24} {icon}  {c['grounded_percentage']:>7.1f}%  "
            f"{c['extrapolation_count']:>4}  "
            f"{c['invention_count']:>4}  "
            f"{c['contradiction_count']:>4}"
        )

    print(f"\n  {'-' * 62}")
    print(
        f"  Totals: {result['total']} cases — "
        f"{result['pass_count']} PASS  "
        f"{result['warn_count']} WARN  "
        f"{result['fail_count']} FAIL  "
        f"(pass rate: {result['pass_rate_pct']:.1f}%)"
    )
    ct = result["claim_type_totals"]
    print(
        f"  Unsupported: "
        f"{ct['EXTRAPOLATION']} extrapolations  "
        f"{ct['INVENTION']} inventions  "
        f"{ct['CONTRADICTION']} contradictions"
    )
    print("=" * _WIDTH)


def _print_verbose(case_result: dict[str, Any]) -> None:
    """Print all unsupported claims for one case."""
    report  = case_result.get("report", {})
    claims  = report.get("unsupported_claims", [])
    verdict = case_result.get("verdict", "?")
    pct     = case_result.get("grounded_percentage", 0.0)

    print(f"\n{'=' * _WIDTH}")
    print(f"  {case_result['case_id']}  —  {case_result.get('name', '')}")
    print(f"  verdict={verdict}  grounded={pct:.1f}%  claims={len(claims)}")
    if report.get("summary"):
        print(f"\n  {report['summary']}")
    print(f"{'=' * _WIDTH}")

    if not claims:
        print("  No unsupported claims found.")
        return

    for i, claim in enumerate(claims, 1):
        icon    = _CLASS_ICONS.get(claim["classification"], "?")
        section = claim.get("section", "unknown")
        print(f"\n  [{i:02d}] [{icon}] {claim['classification']}  —  {section}")
        # Wrap claim text
        claim_text = claim.get("claim", "")
        wrapped = textwrap.fill(
            claim_text, width=_WIDTH - 6,
            initial_indent="       ", subsequent_indent="       "
        )
        print(wrapped)
        if claim.get("explanation"):
            exp = textwrap.fill(
                claim["explanation"], width=_WIDTH - 6,
                initial_indent="       → ", subsequent_indent="         "
            )
            print(exp)

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Grounding checker for SAFe Feature Spec pipeline"
    )
    parser.add_argument(
        "--case",
        metavar="ID",
        help="Run grounding check on a single golden set case (e.g. cap_001_bare)",
    )
    parser.add_argument(
        "--run-id",
        metavar="UUID",
        help="Look up which golden set case a past eval run used, then check it",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to eval SQLite DB",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    init_db(db_path)

    # --run-id: resolve to a golden set case_id via the DB
    case_filter = args.case
    if args.run_id and not case_filter:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT golden_set_id FROM eval_runs WHERE id = ?",
                (args.run_id,),
            ).fetchone()
        if not row:
            print(f"No eval_run found with id={args.run_id!r}", file=sys.stderr)
            sys.exit(1)
        case_filter = row["golden_set_id"]
        print(f"Resolved run_id → golden_set_id: {case_filter}")

    verbose = bool(case_filter)   # single-case always gets verbose output

    print(f"\nRunning grounding checks{'  ('+case_filter+')' if case_filter else ''} …")

    try:
        result = run_grounding_on_golden_set(db_path=db_path, case_filter=case_filter)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if verbose and result["cases"]:
        _print_verbose(result["cases"][0])
    else:
        _print_summary(result)

    any_fail = result["fail_count"] > 0
    sys.exit(1 if any_fail else 0)
