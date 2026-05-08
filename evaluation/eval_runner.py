# evaluation/eval_runner.py
# Day 2 eval runner.
#
# Runs the full pipeline (router → generator → reviewer) for each golden-set entry.
# Skips the Draft Answerer and human-in-the-loop stages — section_answers are pre-filled
# in the golden set.
#
# For each entry:
#   1. classify_feature(description)       — verifies routing
#   2. generate_feature_spec(...)          — builds the spec from section_answers
#   3. review_feature_spec(...)            — scores the spec
#   4. ResultStore.save_run(...)           — persists the result
#   5. TokenTracker.flush_to_db(...)       — persists token usage
#
# Also registers generator and reviewer system prompts as v1 baselines on first run.
#
# Usage:
#   python -m evaluation.eval_runner                  # run all 6 golden set entries
#   python -m evaluation.eval_runner --case cap_001_bare
#   python -m evaluation.eval_runner --verbose        # print full scorecard per case

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from evaluation.eval_db import init_db
from evaluation.golden_set import GOLDEN_SET
from evaluation.prompt_registry import PromptRegistry
from evaluation.result_store import ResultStore
from evaluation.token_tracker import TokenTracker

from agents.router import classify_feature, ROUTER_SYSTEM_PROMPT, ROUTER_SYSTEM_PROMPT_V2
from agents.generator import generate_feature_spec, GENERATOR_SYSTEM_PROMPT
from agents.reviewer import review_feature_spec, REVIEWER_SYSTEM_PROMPT
from prompts import capabilities, experiences, webpages

# Maps feature_type → prompts module (provides PREAMBLE)
_PROMPT_MODULES = {
    "CAPABILITY": capabilities,
    "EXPERIENCE": experiences,
    "WEBPAGE":    webpages,
}


# ---------------------------------------------------------------------------
# Prompt registration
# ---------------------------------------------------------------------------

def register_baseline_prompts(registry: PromptRegistry) -> dict[str, str]:
    """Register the current generator, reviewer, and router system prompts as v1 baselines.

    Also registers the v2 router prompt so it is available for A/B testing.
    Idempotent: re-registering the same prompt text returns the same id
    without creating a duplicate row or bumping the version counter.

    Returns:
        {"generator": prompt_id, "reviewer": prompt_id,
         "router_v1": prompt_id, "router_v2": prompt_id}
    """
    gen_id = registry.register(
        name="generator_v1",
        agent="generator",
        system_prompt=GENERATOR_SYSTEM_PROMPT,
    )
    rev_id = registry.register(
        name="reviewer_v1",
        agent="reviewer",
        system_prompt=REVIEWER_SYSTEM_PROMPT,
    )
    rtr_v1_id = registry.register(
        name="router_v1",
        agent="router",
        system_prompt=ROUTER_SYSTEM_PROMPT,
    )
    rtr_v2_id = registry.register(
        name="router_v2",
        agent="router",
        system_prompt=ROUTER_SYSTEM_PROMPT_V2,
    )
    return {
        "generator": gen_id,
        "reviewer":  rev_id,
        "router_v1": rtr_v1_id,
        "router_v2": rtr_v2_id,
    }


# ---------------------------------------------------------------------------
# Single case runner
# ---------------------------------------------------------------------------

def run_case(
    entry: dict,
    prompt_ids: dict,
    store: ResultStore,
    router_system_prompt: str | None = None,
    use_advisor: bool = False,
) -> dict:
    """Run one golden-set entry through classify → generate → review.

    Args:
        entry:               One entry from GOLDEN_SET (must have section_answers and
                             expected_min_score).
        prompt_ids:          {"generator": id, "reviewer": id, "router_v1": id, ...}
                             from register_baseline_prompts().
        store:               ResultStore instance for persisting results.
        router_system_prompt: Override the router system prompt for A/B testing.
                             Defaults to ROUTER_SYSTEM_PROMPT (v1) if not supplied.

    Returns:
        Summary dict with run_id, scores, routing result, pass/fail, timing, and
        token usage.
    """
    case_id          = entry["id"]
    feature_type     = entry["feature_type"]
    description      = entry["description"]
    section_answers  = entry["section_answers"]
    expected_min     = entry["expected_min_score"]

    tracker = TokenTracker()
    t0 = time.time()

    # ── Step 1: Router ────────────────────────────────────────────────────────
    classified_type = classify_feature(description, tracker, system_prompt=router_system_prompt)

    # ── Step 2: Generator ─────────────────────────────────────────────────────
    module = _PROMPT_MODULES[feature_type]
    spec = generate_feature_spec(
        feature_type=feature_type,
        preamble=module.PREAMBLE,
        section_answers=section_answers,
        tracker=tracker,
    )

    # ── Step 3: Reviewer ──────────────────────────────────────────────────────
    scorecard = review_feature_spec(spec, feature_type=feature_type, tracker=tracker, use_advisor=use_advisor)

    elapsed = round(time.time() - t0, 1)

    # ── Step 4: Persist ───────────────────────────────────────────────────────
    total_score = scorecard.get("total_score", 0)
    has_parse_error = "parse_error" in scorecard
    passed = (not has_parse_error) and (total_score >= expected_min)

    # Determine which router prompt_id was used (v2 if override supplied, else v1).
    active_router_prompt_id = (
        prompt_ids.get("router_v2")
        if router_system_prompt is not None and router_system_prompt != ROUTER_SYSTEM_PROMPT
        else prompt_ids.get("router_v1")
    )

    run_id = store.save_run(
        golden_set_id=case_id,
        feature_type=feature_type,
        scorecard=scorecard,
        prompt_id=prompt_ids.get("reviewer"),
        router_prompt_id=active_router_prompt_id,
        classified_as=classified_type,
        original_score=total_score,
        final_score=total_score,   # No improvement pass in the eval runner
        passed=passed,
    )
    tracker.flush_to_db(run_id)

    return {
        "case_id":          case_id,
        "run_id":           run_id,
        "name":             entry.get("name", case_id),
        "feature_type":     feature_type,
        "classified_as":    classified_type,
        "routing_correct":  classified_type == feature_type,
        "total_score":      total_score,
        "expected_min":     expected_min,
        "passed":           passed,
        "has_parse_error":  has_parse_error,
        "elapsed_s":        elapsed,
        "token_summary":    tracker.summary(),
        "scorecard":        scorecard,
    }


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _section_line(title: str, width: int = 65) -> None:
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def print_verbose_scorecard(result: dict) -> None:
    """Print a per-section breakdown for one result."""
    scorecard = result["scorecard"]
    if "parse_error" in scorecard:
        print(f"    [PARSE ERROR] {scorecard['parse_error']}")
        return

    print(f"    {'Section':<45} {'Score':>6}  {'Max':>4}  {'%':>4}")
    print(f"    {'-' * 62}")
    for section_name, data in scorecard.get("sections", {}).items():
        score   = data.get("score", 0)
        max_pts = data.get("max_points", 0)
        pct     = round(score / max_pts * 100) if max_pts > 0 else 0
        flag    = "⚠" if pct < 75 else " "
        rec     = data.get("recommendations", "")
        print(f"    {flag} {section_name:<44} {score:>5}/{max_pts:<4} {pct:>3}%")
        if rec:
            # Wrap recommendation text at ~60 chars
            words = rec.split()
            line = "      → "
            for word in words:
                if len(line) + len(word) > 68:
                    print(line)
                    line = "        " + word + " "
                else:
                    line += word + " "
            if line.strip():
                print(line)


def print_summary(results: list[dict]) -> None:
    """Print a formatted summary table for all results."""
    _section_line("RESULTS SUMMARY")
    print(
        f"  {'CASE ID':<22} {'TYPE':<12} {'SCORE':>5}  {'MIN':>3}  "
        f"{'PASS':<7}  {'TIME':>5}  ROUTING"
    )
    print(f"  {'-' * 62}")

    for r in results:
        if "error" in r:
            print(f"  {r['case_id']:<22} {'ERROR':<12}  {'--':>5}  {'--':>3}  [FAIL]   {'--':>5}")
            continue

        icon    = "[OK]  " if r["passed"] else "[FAIL]"
        routing = "OK" if r["routing_correct"] else f"→{r['classified_as']}"
        score_s = f"{r['total_score']}/100"
        if r.get("has_parse_error"):
            score_s = "PARSE ERR"

        print(
            f"  {r['case_id']:<22} {r['feature_type']:<12} {score_s:>5}  "
            f"{r['expected_min']:>3}  {icon}  {r['elapsed_s']:>4}s  {routing}"
        )

    print(f"  {'-' * 62}")

    good     = [r for r in results if r.get("passed")]
    bad      = [r for r in results if not r.get("passed")]
    total    = len(results)
    cost_usd = sum(r.get("token_summary", {}).get("cost_usd", 0.0) for r in results)

    print(f"\n  Results : {len(good)}/{total} passed")
    print(f"  API cost: ${cost_usd:.4f}")

    if bad:
        print("\n  FAILURES:")
        for r in bad:
            if "error" in r:
                print(f"    {r['case_id']}: exception — {r['error']}")
            elif r.get("has_parse_error"):
                print(f"    {r['case_id']}: reviewer parse error")
            else:
                print(
                    f"    {r['case_id']}: score {r['total_score']} "
                    f"< min {r['expected_min']}"
                )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(
    case_filter: str | None = None,
    verbose: bool = False,
    router_version: str = "v1",
    use_advisor: bool = False,
) -> list[dict]:
    """Run eval against all (or one) golden-set entries.

    Args:
        case_filter:    If set, only the entry with this id is run.
        verbose:        If True, print per-section scorecard after each case.
        router_version: "v1" (default) or "v2" — selects the router system prompt.

    Returns:
        List of result dicts (one per case run).
    """
    init_db()

    registry = PromptRegistry()
    store    = ResultStore()

    # Register current system prompts as baselines (idempotent).
    prompt_ids = register_baseline_prompts(registry)

    router_system_prompt = ROUTER_SYSTEM_PROMPT_V2 if router_version == "v2" else None
    print(
        f"Prompts registered — "
        f"generator: {prompt_ids['generator'][:8]}  "
        f"reviewer:  {prompt_ids['reviewer'][:8]}  "
        f"router: {router_version} ({(prompt_ids.get('router_v2') if router_version == 'v2' else prompt_ids.get('router_v1', ''))[:8]})"
    )

    # Apply case filter.
    cases = GOLDEN_SET
    if case_filter:
        cases = [c for c in GOLDEN_SET if c["id"] == case_filter]
        if not cases:
            ids = [c["id"] for c in GOLDEN_SET]
            print(f"No golden-set entry with id={case_filter!r}. Available: {ids}")
            sys.exit(1)

    # Run each case.
    results: list[dict] = []
    for entry in cases:
        print(f"\nRunning {entry['id']}  ({entry.get('name', '')})")
        try:
            result = run_case(entry, prompt_ids, store, router_system_prompt=router_system_prompt, use_advisor=use_advisor)
            results.append(result)

            score_s = (
                "PARSE ERR"
                if result["has_parse_error"]
                else f"{result['total_score']}/100"
            )
            icon     = "[OK]" if result["passed"] else "[FAIL]"
            routing  = "routing OK" if result["routing_correct"] else f"routed→{result['classified_as']}"
            cost_s   = f"${result['token_summary']['cost_usd']:.4f}"

            print(
                f"  score={score_s}  min={result['expected_min']}  "
                f"{icon}  {result['elapsed_s']}s  {routing}  {cost_s}"
            )

            if verbose:
                print_verbose_scorecard(result)

        except Exception as exc:
            print(f"  ERROR: {exc}")
            results.append({"case_id": entry["id"], "passed": False, "error": str(exc)})

    print_summary(results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SAFe Feature Spec eval runner — Day 2"
    )
    parser.add_argument(
        "--case",
        metavar="ID",
        help="Run a single golden-set entry by id (e.g. cap_001_bare)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print per-section scorecard breakdown after each case",
    )
    parser.add_argument(
        "--router",
        metavar="VERSION",
        choices=["v1", "v2"],
        default="v1",
        help="Router prompt version to use: v1 (default) or v2",
    )
    parser.add_argument(
        "--advisor",
        action="store_true",
        help="Enable Opus advisor for Reviewer and Improver",
    )
    args = parser.parse_args()
    main(case_filter=args.case, verbose=args.verbose, router_version=args.router, use_advisor=args.advisor)
