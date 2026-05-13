"""
PM review data layer. No Streamlit — pure data structures and transformation logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from intake_copilot.models import IntakeRecord, FieldStatus


@dataclass
class PMReviewRecord:
    # ---- copilot outputs ---------------------------------------------------
    intake_record: IntakeRecord
    recommendation: dict[str, Any]
    conversation_transcript: list[dict[str, str]]
    stakeholder_raw_input: str

    # ---- PM decisions (None until PM acts) ---------------------------------
    pm_feature_type: Optional[str] = None          # "CAPABILITY" | "EXPERIENCE" | "WEBPAGE"
    pm_boost_inputs: Optional[str] = None
    pm_decision: Optional[str] = None              # "accept" | "reject"
    pm_rejection_reason: Optional[str] = None
    pm_field_edits: Optional[dict[str, str]] = field(default_factory=dict)

    # -----------------------------------------------------------------------
    # PM actions
    # -----------------------------------------------------------------------

    def set_feature_type(self, feature_type: str) -> None:
        ft = feature_type.upper()
        if ft not in ("CAPABILITY", "EXPERIENCE", "WEBPAGE"):
            raise ValueError(f"Invalid feature type: {feature_type!r}")
        self.pm_feature_type = ft

    def add_boost_inputs(self, text: str) -> None:
        self.pm_boost_inputs = text.strip() or None

    def edit_field(self, field_name: str, value: str) -> None:
        if self.pm_field_edits is None:
            self.pm_field_edits = {}
        self.pm_field_edits[field_name] = value

    def accept(self) -> None:
        if not self.pm_feature_type:
            raise ValueError("Feature type must be confirmed before accepting.")
        self.pm_decision = "accept"

    def reject(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("Rejection reason cannot be empty.")
        self.pm_decision = "reject"
        self.pm_rejection_reason = reason.strip()

    # -----------------------------------------------------------------------
    # Generator handoff
    # -----------------------------------------------------------------------

    def to_generator_input(self) -> dict[str, Any]:
        """
        Transform the accepted record into the format agents/generator.py expects.
        Only callable after accept().
        """
        if self.pm_decision != "accept":
            raise RuntimeError("to_generator_input() called before accept().")

        record = self.intake_record
        edits = self.pm_field_edits or {}

        def fv(f_name: str) -> str:
            if f_name in edits:
                return edits[f_name]
            f = getattr(record, f_name)
            # Use f.value if non-empty — matches what the PM review display shows.
            # is_populated() can return False when value is set but status wasn't
            # updated (e.g. feature_type set via feature_type_guess path).
            if f.value:
                return f.value
            if f.status.value == "unknown":
                return f"[NEEDS INPUT: stakeholder does not know — {f_name}]"
            return f"[NEEDS INPUT: {f_name}]"

        def _sentence(text: str) -> str:
            """Ensure text ends with exactly one period."""
            return text.rstrip(". ") + "."

        # Synthesise a coherent feature_description paragraph.
        # Optional fields (dependencies, timeline) are omitted when unpopulated.
        feature_name_val = fv("feature_name")
        approach_val = fv("solution_approach")
        problem_val = fv("problem_statement")
        audience_val = fv("target_audience")
        objective_val = fv("business_objective")
        metrics_val = fv("success_metrics")
        deps_val = fv("dependencies")
        timeline_val = fv("timeline_constraints")

        parts = [
            f"{feature_name_val}: {_sentence(approach_val)}",
            f"This addresses the following need: {_sentence(problem_val)}",
            f"Target users: {_sentence(audience_val)}",
            f"Business objective: {_sentence(objective_val)}",
            f"Success metrics: {_sentence(metrics_val)}",
        ]
        if not deps_val.startswith("[NEEDS INPUT"):
            parts.append(f"Constraints and dependencies: {_sentence(deps_val)}")
        if not timeline_val.startswith("[NEEDS INPUT"):
            parts.append(f"Timeline: {_sentence(timeline_val)}")

        feature_description = " ".join(parts)

        # Boost inputs: PM-entered text + scope exclusions only.
        # additional_context is already in section_answers["Additional Context"]
        # and must not be duplicated here.
        boost_parts: list[str] = []
        if self.pm_boost_inputs:
            boost_parts.append(self.pm_boost_inputs)

        excl = fv("scope_exclusions")
        if not excl.startswith("[NEEDS INPUT"):
            boost_parts.append(f"Out of scope: {excl}")

        boost_inputs = "\n\n".join(boost_parts) or None

        # section_answers: use PM edits and confirmed feature type throughout.
        section_answers: dict[str, str] = {
            "Feature Overview": (
                f"Feature Name: {fv('feature_name')}\n"
                f"Feature Type: {self.pm_feature_type}\n"
                f"Problem Statement: {fv('problem_statement')}\n"
                f"Business Objective: {fv('business_objective')}"
            ),
            "Audience & Metrics": (
                f"Target Audience: {fv('target_audience')}\n"
                f"Success Metrics: {fv('success_metrics')}"
            ),
            "Scope & Approach": (
                f"Solution Approach: {fv('solution_approach')}\n"
                f"In Scope: {fv('scope_inclusions')}\n"
                f"Out of Scope: {fv('scope_exclusions')}"
            ),
            "Dependencies & Constraints": (
                f"Dependencies: {fv('dependencies')}\n"
                f"Timeline Constraints: {fv('timeline_constraints')}"
            ),
            "Additional Context": fv("additional_context"),
        }

        return {
            "feature_description": feature_description,
            "feature_type": self.pm_feature_type,
            "notes": self.stakeholder_raw_input,
            "boost_inputs": boost_inputs,
            "skip_router": True,
            "section_answers": section_answers,
        }
