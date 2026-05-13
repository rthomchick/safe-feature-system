# intake_copilot/pipeline_bridge.py
"""
Bridge between PMReviewRecord.to_generator_input() and the existing SAFe pipeline.

The pipeline normally runs: Router → Draft Answerer → Generator → Reviewer → Improver.
When intake comes from the copilot, the PM has already confirmed the feature type,
so the Router is bypassed (skip_router=True in the generator_input dict).

The Draft Answerer is also bypassed: the copilot already produced section_answers
via IntakeRecord.to_generator_input(), which is richer than what the Draft Answerer
would produce from raw notes.

Pipeline executed here:
    Generator → Reviewer → (Improver × 2 if weak sections) → (Polish if 80-89)
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from prompts import capabilities, experiences, webpages
from agents.generator import generate_feature_spec
from agents.reviewer import review_feature_spec, review_sections
from agents.improver import improve_spec, polish_spec
from evaluation.token_tracker import TokenTracker
from evaluation.audit_trail import AuditTrail, GENERATE, REVIEW, IMPROVE
from evaluation.cost_guardrails import CostGuard, CostLimitExceeded
from evaluation.result_store import ResultStore
from evaluation.eval_db import init_db

_PROMPT_MODULES = {
    "CAPABILITY": capabilities,
    "EXPERIENCE": experiences,
    "WEBPAGE": webpages,
}

# The improver's additional_context dict is keyed by full rubric section names.
# PM boost_inputs (free-form) is attached here as a catch-all.
_BOOST_FALLBACK_SECTION = "I. Feature Definition & Objective"


def _merge_scorecards(
    base: dict,
    partial: dict,
    changed: set[str],
) -> dict:
    merged: dict[str, Any] = {"sections": {}}
    for name, data in base.get("sections", {}).items():
        if name in changed and name in partial.get("sections", {}):
            new_data = dict(partial["sections"][name])
            base_score = data.get("score", 0)
            max_pts = data.get("max_points", new_data.get("max_points", 100))
            new_data["score"] = min(max(new_data.get("score", 0), base_score), max_pts)
            merged["sections"][name] = new_data
        else:
            merged["sections"][name] = data
    merged["total_score"] = sum(
        s.get("score", 0) for s in merged["sections"].values()
    )
    return merged


def run_pipeline_from_intake(
    generator_input: dict,
    tracker: Optional[TokenTracker] = None,
    use_advisor: bool = False,
) -> dict:
    """
    Execute the SAFe pipeline from a PMReviewRecord.to_generator_input() dict.

    Args:
        generator_input: Output of PMReviewRecord.to_generator_input(). Expected keys:
            feature_type    — "CAPABILITY" | "EXPERIENCE" | "WEBPAGE"
            section_answers — {section_name: answer_text}
            boost_inputs    — str | None  (PM-added context for the Reviewer stage)
            feature_description — synthesised paragraph (informational, not used by generator)
            notes           — raw stakeholder text (informational)
            skip_router     — bool (always True from to_generator_input)
        tracker:   Optional TokenTracker; one is created if not supplied.
        use_advisor: Pass Opus advisor to Reviewer and Improver.

    Returns:
        {
            "run_id": str,
            "spec": str,                  # final spec (post-improvement)
            "scorecard": dict,            # final scorecard
            "original_score": int,
            "final_score": int,
            "cost_usd": float,
            "token_summary": dict,
        }
        On failure:
        {
            "error": True,
            "stage": str,                 # which stage failed
            "message": str,
        }
    """
    init_db()

    feature_type: str = generator_input.get("feature_type", "").upper()
    if feature_type not in _PROMPT_MODULES:
        return {
            "error": True,
            "stage": "validation",
            "message": f"Unknown feature type: {feature_type!r}. Must be CAPABILITY, EXPERIENCE, or WEBPAGE.",
        }

    section_answers: dict = generator_input.get("section_answers", {})
    boost_inputs: Optional[str] = generator_input.get("boost_inputs")

    if tracker is None:
        tracker = TokenTracker()

    run_id = str(uuid.uuid4())
    trail = AuditTrail()
    guard = CostGuard()
    module = _PROMPT_MODULES[feature_type]

    store = ResultStore()
    store.save_run(
        golden_set_id="intake_copilot",
        feature_type=feature_type,
        scorecard={},
        run_id=run_id,
        original_score=0,
        final_score=0,
        passed=None,
    )

    # ── Stage: Generate ───────────────────────────────────────────────────────
    try:
        guard.sync_from_tracker(tracker)
        guard.check_before_call("generator")
        spec = generate_feature_spec(
            feature_type=feature_type,
            preamble=module.PREAMBLE,
            section_answers=section_answers,
            tracker=tracker,
        )
    except CostLimitExceeded as e:
        return {"error": True, "stage": "generator", "message": f"Cost limit: {e}"}
    except Exception as e:
        return {"error": True, "stage": "generator", "message": str(e)}

    trail.log_event(run_id, GENERATE, {
        "feature_type": feature_type,
        "section_count": len(section_answers),
        "output_length_chars": len(spec),
    })

    # ── Stage: Review ─────────────────────────────────────────────────────────
    try:
        guard.sync_from_tracker(tracker)
        guard.check_before_call("reviewer")
        scorecard = review_feature_spec(
            spec,
            feature_type=feature_type,
            use_advisor=use_advisor,
            tracker=tracker,
        )
    except CostLimitExceeded as e:
        return {"error": True, "stage": "reviewer", "message": f"Cost limit: {e}"}
    except Exception as e:
        return {"error": True, "stage": "reviewer", "message": str(e)}

    if "parse_error" in scorecard:
        return {
            "error": True,
            "stage": "reviewer",
            "message": f"Reviewer parse error: {scorecard['parse_error']}",
        }

    original_score = scorecard.get("total_score", 0)
    trail.log_event(run_id, REVIEW, {
        "total_score": original_score,
        "passed": original_score >= 90,
    })

    # ── Build additional_context for the Improver ─────────────────────────────
    # boost_inputs is free-form PM text; attach it to the catch-all rubric section.
    # The Improver only reads additional_context for sections it is targeting,
    # so this only fires when that section is actually weak.
    additional_context: dict[str, str] = {}
    if boost_inputs:
        additional_context[_BOOST_FALLBACK_SECTION] = boost_inputs

    # ── Stage: Improve (pass 1) ───────────────────────────────────────────────
    weak_sections = {
        name for name, data in scorecard.get("sections", {}).items()
        if data.get("max_points", 0) > 0
        and data.get("score", 0) / data["max_points"] < 0.75
    }

    improved_spec = spec
    improved_scorecard = scorecard

    if weak_sections:
        try:
            guard.sync_from_tracker(tracker)
            guard.check_before_call("improver")
            improved_spec = improve_spec(
                spec,
                scorecard,
                additional_context,
                use_advisor=use_advisor,
                tracker=tracker,
            )
        except CostLimitExceeded as e:
            return {"error": True, "stage": "improver_pass1", "message": f"Cost limit: {e}"}
        except Exception as e:
            return {"error": True, "stage": "improver_pass1", "message": str(e)}

        changed = set(improve_spec.last_debug.get("weak_rubric_sections", []))

        try:
            guard.sync_from_tracker(tracker)
            guard.check_before_call("reviewer")
            partial = review_sections(
                improved_spec, list(changed),
                feature_type=feature_type,
                use_advisor=use_advisor,
                tracker=tracker,
            ) if changed else {"sections": {}}
        except CostLimitExceeded as e:
            return {"error": True, "stage": "reviewer_pass1", "message": f"Cost limit: {e}"}
        except Exception as e:
            return {"error": True, "stage": "reviewer_pass1", "message": str(e)}

        improved_scorecard = _merge_scorecards(scorecard, partial, changed)
        trail.log_event(run_id, IMPROVE, {
            "iteration": 1,
            "sections_targeted": list(changed),
            "score_before": original_score,
            "score_after": improved_scorecard.get("total_score", 0),
        })

        # ── Improve pass 2: only still-weak sections that were originally weak ─
        still_weak_originally_weak = [
            name for name, data in improved_scorecard.get("sections", {}).items()
            if name in weak_sections
            and data.get("max_points", 0) > 0
            and data.get("score", 0) / data["max_points"] < 0.75
        ]
        first_score = improved_scorecard.get("total_score", 0)
        regressions = [
            name for name, data in improved_scorecard.get("sections", {}).items()
            if name not in weak_sections
            and data.get("max_points", 0) > 0
            and data.get("score", 0) / data["max_points"] < 0.75
        ]

        if still_weak_originally_weak and not regressions and first_score > original_score:
            filtered_scorecard = {
                "total_score": first_score,
                "sections": {
                    k: v for k, v in improved_scorecard["sections"].items()
                    if k in weak_sections
                },
            }
            try:
                guard.sync_from_tracker(tracker)
                guard.check_before_call("improver")
                improved_spec = improve_spec(
                    improved_spec,
                    filtered_scorecard,
                    additional_context,
                    use_advisor=use_advisor,
                    tracker=tracker,
                )
            except CostLimitExceeded as e:
                # Pass 2 failure is non-fatal — keep pass 1 result.
                pass
            except Exception:
                pass
            else:
                changed2 = set(improve_spec.last_debug.get("weak_rubric_sections", []))
                try:
                    partial2 = review_sections(
                        improved_spec, list(changed2),
                        feature_type=feature_type,
                        use_advisor=use_advisor,
                        tracker=tracker,
                    ) if changed2 else {"sections": {}}
                    improved_scorecard = _merge_scorecards(
                        improved_scorecard, partial2, changed2
                    )
                except Exception:
                    pass

                trail.log_event(run_id, IMPROVE, {
                    "iteration": 2,
                    "sections_targeted": list(changed2),
                    "score_before": first_score,
                    "score_after": improved_scorecard.get("total_score", 0),
                })

    # ── Stage: Polish (80–89 range) ───────────────────────────────────────────
    tier2_total = improved_scorecard.get("total_score", 0)
    if 80 <= tier2_total < 90 and "parse_error" not in improved_scorecard:
        try:
            guard.sync_from_tracker(tracker)
            guard.check_before_call("improver")
            polished = polish_spec(
                improved_spec,
                improved_scorecard,
                additional_context,
                use_advisor=use_advisor,
                tracker=tracker,
            )
            polish_changed = set(polish_spec.last_debug.get("polish_candidates", []))
            if polish_changed:
                partial_polish = review_sections(
                    polished, list(polish_changed),
                    feature_type=feature_type,
                    use_advisor=use_advisor,
                    tracker=tracker,
                )
                improved_scorecard = _merge_scorecards(
                    improved_scorecard, partial_polish, polish_changed
                )
                improved_spec = polished
        except Exception:
            # Polish is best-effort; failure doesn't block the result.
            pass

    # ── Persist result ────────────────────────────────────────────────────────
    final_score = improved_scorecard.get("total_score", original_score)

    store.update_run(
        run_id,
        feature_type=feature_type,
        scorecard=improved_scorecard,
        original_score=original_score,
        final_score=final_score,
        passed=final_score >= 90,
    )
    tracker.flush_to_db(run_id)

    token_summary = tracker.summary()

    return {
        "run_id": run_id,
        "spec": improved_spec,
        "scorecard": improved_scorecard,
        "original_score": original_score,
        "final_score": final_score,
        "cost_usd": token_summary.get("cost_usd", 0.0),
        "token_summary": token_summary,
    }
