# evaluation/ab_test_router.py
# Router prompt A/B test — v1 vs v2.
#
# Calls classify_feature() with both router system prompts for each golden-set
# entry. Skips generation and review — routing only, so this is fast and cheap
# (Haiku at temperature 0, one call per case per version = 12 calls total).
#
# Registers both router prompts in the PromptRegistry (idempotent).
#
# Usage:
#   python -m evaluation.ab_test_router                  # all 6 cases
#   python -m evaluation.ab_test_router --case exp_001_bare
#   python -m evaluation.ab_test_router --verbose        # show raw responses

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from evaluation.eval_db import init_db
from evaluation.golden_set import GOLDEN_SET
from evaluation.prompt_registry import PromptRegistry
from evaluation.token_tracker import TokenTracker

from agents.router import (
    classify_feature,
    ROUTER_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT_V2,
)


# ---------------------------------------------------------------------------
# Core comparison logic
# ---------------------------------------------------------------------------

def run_routing_comparison(
    entry: dict,
    registry: PromptRegistry,
    verbose: bool = False,
) -> dict:
    """Classify one entry with both v1 and v2 router prompts.

    Returns:
        {
            "case_id":        str,
            "feature_type":   str,
            "v1_result":      str,
            "v2_result":      str,
            "v1_correct":     bool,
            "v2_correct":     bool,
            "v1_elapsed_ms":  int,
            "v2_elapsed_ms":  int,
        }
    """
    case_id      = entry["id"]
    feature_type = entry["feature_type"]
    description  = entry["description"]

    tracker_v1 = TokenTracker()
    t0 = time.time()
    v1_result = classify_feature(description, tracker_v1, system_prompt=ROUTER_SYSTEM_PROMPT)
    v1_elapsed_ms = round((time.time() - t0) * 1000)

    tracker_v2 = TokenTracker()
    t0 = time.time()
    v2_result = classify_feature(description, tracker_v2, system_prompt=ROUTER_SYSTEM_PROMPT_V2)
    v2_elapsed_ms = round((time.time() - t0) * 1000)

    if verbose:
        print(f"    [{case_id}] v1→{v1_result}  v2→{v2_result}  (expected: {feature_type})")

    return {
        "case_id":       case_id,
        "name":          entry.get("name", case_id),
        "feature_type":  feature_type,
        "v1_result":     v1_result,
        "v2_result":     v2_result,
        "v1_correct":    v1_result == feature_type,
        "v2_correct":    v2_result == feature_type,
        "v1_elapsed_ms": v1_elapsed_ms,
        "v2_elapsed_ms": v2_elapsed_ms,
        "v1_tokens":     tracker_v1.summary(),
        "v2_tokens":     tracker_v2.summary(),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_comparison_table(results: list[dict]) -> None:
    width = 70
    print(f"\n{'=' * width}")
    print(f"  Router A/B Test — v1 vs v2")
    print(f"{'=' * width}")
    print(
        f"  {'CASE ID':<24} {'TYPE':<12} {'V1':>10}  {'V2':>10}"
    )
    print(f"  {'-' * 60}")

    for r in results:
        if "error" in r:
            print(f"  {r['case_id']:<24} {'ERROR':<12}  {'--':>10}  {'--':>10}")
            continue

        def fmt(result: str, correct: bool, expected: str) -> str:
            if correct:
                return "OK"
            return f"FAIL→{result}"

        v1_s = fmt(r["v1_result"], r["v1_correct"], r["feature_type"])
        v2_s = fmt(r["v2_result"], r["v2_correct"], r["feature_type"])

        # Highlight regressions (v2 wrong where v1 was right) or fixes (v2 right where v1 wrong)
        changed = r["v1_correct"] != r["v2_correct"]
        marker = " ◄" if changed else ""

        print(
            f"  {r['case_id']:<24} {r['feature_type']:<12} {v1_s:>10}  {v2_s:>10}{marker}"
        )

    print(f"  {'-' * 60}")

    good_v1  = sum(1 for r in results if r.get("v1_correct"))
    good_v2  = sum(1 for r in results if r.get("v2_correct"))
    total    = len(results)
    cost_v1  = sum(r.get("v1_tokens", {}).get("cost_usd", 0.0) for r in results)
    cost_v2  = sum(r.get("v2_tokens", {}).get("cost_usd", 0.0) for r in results)

    print(f"\n  Routing accuracy:")
    print(f"    v1: {good_v1}/{total}  (${cost_v1:.4f})")
    print(f"    v2: {good_v2}/{total}  (${cost_v2:.4f})")

    # Highlight regressions or fixes
    fixes = [r for r in results if not r.get("v1_correct") and r.get("v2_correct")]
    regressions = [r for r in results if r.get("v1_correct") and not r.get("v2_correct")]

    if fixes:
        print(f"\n  Fixed by v2:")
        for r in fixes:
            print(f"    {r['case_id']}: {r['v1_result']} → {r['v2_result']} (expected {r['feature_type']})")

    if regressions:
        print(f"\n  Regressions in v2:")
        for r in regressions:
            print(f"    {r['case_id']}: {r['v1_result']} → {r['v2_result']} (expected {r['feature_type']})")

    if not fixes and not regressions:
        print("\n  No changes between v1 and v2.")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(case_filter: str | None = None, verbose: bool = False) -> list[dict]:
    """Run A/B routing comparison for all (or one) golden-set entries.

    Args:
        case_filter: If set, only the entry with this id is run.
        verbose:     If True, print per-case raw routing result as it runs.

    Returns:
        List of comparison result dicts.
    """
    init_db()

    registry = PromptRegistry()
    v1_id = registry.register(name="router_v1", agent="router", system_prompt=ROUTER_SYSTEM_PROMPT)
    v2_id = registry.register(name="router_v2", agent="router", system_prompt=ROUTER_SYSTEM_PROMPT_V2)
    print(
        f"Router prompts registered — v1: {v1_id[:8]}  v2: {v2_id[:8]}"
    )

    cases = GOLDEN_SET
    if case_filter:
        cases = [c for c in GOLDEN_SET if c["id"] == case_filter]
        if not cases:
            ids = [c["id"] for c in GOLDEN_SET]
            print(f"No golden-set entry with id={case_filter!r}. Available: {ids}")
            sys.exit(1)

    results: list[dict] = []
    for entry in cases:
        print(f"  Classifying {entry['id']} ...")
        try:
            result = run_routing_comparison(entry, registry, verbose=verbose)
            results.append(result)
        except Exception as exc:
            print(f"    ERROR: {exc}")
            results.append({"case_id": entry["id"], "error": str(exc)})

    print_comparison_table(results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Router prompt A/B test — v1 vs v2 routing accuracy"
    )
    parser.add_argument(
        "--case",
        metavar="ID",
        help="Run a single golden-set entry by id (e.g. exp_001_bare)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print raw v1/v2 results as each case runs",
    )
    args = parser.parse_args()
    main(case_filter=args.case, verbose=args.verbose)
