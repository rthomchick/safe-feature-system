"""
Responsible AI checklist for the SAFe Feature Spec System.

Each category captures a dimension of responsible AI practice with:
  - description: what the category covers
  - checks: specific, verifiable items within that dimension
  - status: IMPLEMENTED, PARTIAL, or MISSING (reflects current eval infra state)

Status key:
  IMPLEMENTED — fully addressed by existing infra (token_tracker, prompt_registry,
                 eval_db, golden_set, ab_test_router)
  PARTIAL     — partially addressed; gaps noted in check descriptions
  MISSING     — no current coverage; identified as next implementation target
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Status(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"


@dataclass
class CheckCategory:
    name: str
    description: str
    checks: List[str]
    status: Status


CHECKLIST: List[CheckCategory] = [
    CheckCategory(
        name="fairness",
        description=(
            "Ensure the system produces equitable outputs across input types, "
            "domains, and user contexts — no systematic quality gap between "
            "engineering vs. product vs. marketing feature requests."
        ),
        checks=[
            "Golden set spans multiple feature categories (capability, UX, experience)",
            "Eval runner scores each category independently and surfaces per-category means",
            "Cross-category score comparison flags categories with mean score < overall mean - 1 stddev",
            "Bias detection: automated alert when any category consistently underperforms others",
        ],
        status=Status.PARTIAL,
        # Golden set and per-category scoring exist; cross-category comparison
        # and automated bias alerts are not yet implemented.
    ),

    CheckCategory(
        name="reliability",
        description=(
            "Verify that the system produces consistently high-quality outputs "
            "across runs, prompt versions, and model changes — with regression "
            "detection to catch quality degradation before it reaches production."
        ),
        checks=[
            "Eval DB stores scored outputs for every run against the golden set",
            "Prompt registry versions every prompt; version is recorded per eval run",
            "Smoke test covers the full agent pipeline end-to-end",
            "Regression guard: eval runner fails the run if mean score drops > N points vs. prior baseline",
            "A/B test router compares routing strategies and surfaces win/loss metrics",
        ],
        status=Status.IMPLEMENTED,
        # eval_db, prompt_registry, smoke_test, eval_runner, and ab_test_router
        # collectively cover all checks above.
    ),

    CheckCategory(
        name="transparency",
        description=(
            "Make system behavior explainable and inspectable — prompt versions, "
            "model choices, scoring rationale, and per-run decisions must be "
            "traceable by any team member reviewing outputs."
        ),
        checks=[
            "Every eval result is linked to the prompt version used (prompt_registry)",
            "Scoring rubric is stored alongside results in the eval DB",
            "Dashboard exposes per-run metadata: model, prompt hash, score breakdown",
            "Audit trail: per-run decision trace capturing agent path, tool calls, and intermediate outputs",
        ],
        status=Status.PARTIAL,
        # Prompt versioning and scoring storage are implemented. A full per-run
        # decision trace (agent path + tool calls) is not yet captured.
    ),

    CheckCategory(
        name="cost_governance",
        description=(
            "Track, bound, and alert on token spend to prevent runaway costs "
            "and enable data-driven decisions about model selection and prompt efficiency."
        ),
        checks=[
            "Token usage tracked per run (input tokens, output tokens, estimated cost)",
            "Token tracker aggregates cost by model, prompt version, and eval suite",
            "Cost guardrails: configurable per-run spend limit that aborts execution if exceeded",
            "Spend alerts: notification when cumulative eval spend crosses a threshold",
        ],
        status=Status.PARTIAL,
        # token_tracker.py implements per-run tracking and aggregation. Hard
        # spend limits and alert notifications are not yet implemented.
    ),

    CheckCategory(
        name="safety",
        description=(
            "Detect and prevent harmful, hallucinated, or ungrounded outputs — "
            "spec content must be traceable to the input and must not fabricate "
            "metrics, team names, or architectural claims."
        ),
        checks=[
            "Output schema validation ensures required spec sections are present",
            "Grounding check: verify that factual claims in the spec are entailed by the input",
            "Hallucination detection: flag outputs that introduce named metrics or systems absent from input",
            "Human review gate for any output flagged by grounding or hallucination checks",
        ],
        status=Status.MISSING,
        # No grounding or hallucination detection is currently implemented.
        # Schema validation exists implicitly via section parsing in the improver
        # but is not a formal safety gate.
    ),

    CheckCategory(
        name="versioning",
        description=(
            "Maintain a complete, reproducible history of prompts, model configs, "
            "and eval baselines so that any past result can be reproduced and "
            "any change can be attributed to a specific modification."
        ),
        checks=[
            "Prompt registry assigns a content-hash version to every prompt",
            "Eval results stored with prompt version, model ID, and timestamp",
            "Prompt diffs surfaced when a new version is registered",
            "Baseline snapshots: eval DB records a named baseline per prompt version for regression comparison",
        ],
        status=Status.IMPLEMENTED,
        # prompt_registry.py and eval_db.py together cover all four checks.
        # Baseline snapshots are stored implicitly as the first run per prompt
        # version; explicit named baselines are a minor gap but functional.
    ),
]


def print_checklist() -> None:
    """Print a human-readable summary of the responsible AI checklist."""
    status_symbols = {
        Status.IMPLEMENTED: "[x]",
        Status.PARTIAL:     "[~]",
        Status.MISSING:     "[ ]",
    }
    width = 72

    print("=" * width)
    print("RESPONSIBLE AI CHECKLIST — SAFe Feature Spec System")
    print("=" * width)

    for category in CHECKLIST:
        symbol = status_symbols[category.status]
        print(f"\n{symbol} {category.name.upper()}  ({category.status.value})")
        print(f"    {category.description}")
        print()
        for check in category.checks:
            print(f"      • {check}")

    print("\n" + "=" * width)
    totals = {s: sum(1 for c in CHECKLIST if c.status == s) for s in Status}
    print(
        f"Summary: "
        f"{totals[Status.IMPLEMENTED]} IMPLEMENTED  "
        f"{totals[Status.PARTIAL]} PARTIAL  "
        f"{totals[Status.MISSING]} MISSING"
    )
    print("=" * width)


if __name__ == "__main__":
    print_checklist()
