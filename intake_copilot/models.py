"""
Data layer for the intake copilot. No API calls — pure data structures and logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class FieldStatus(Enum):
    POPULATED = "populated"
    UNKNOWN = "unknown"       # stakeholder said "I don't know"
    UNASKED = "unasked"       # copilot chose not to ask


# ---------------------------------------------------------------------------
# IntakeField
# ---------------------------------------------------------------------------

@dataclass
class IntakeField:
    name: str
    value: Optional[str] = None
    status: FieldStatus = FieldStatus.UNASKED
    weight: int = 1
    tier: str = "detail"      # "core" | "context" | "detail"

    def is_populated(self) -> bool:
        return self.status == FieldStatus.POPULATED and self.value is not None


# ---------------------------------------------------------------------------
# IntakeRecord
# ---------------------------------------------------------------------------

@dataclass
class IntakeRecord:
    # ---- raw inputs -------------------------------------------------------
    stakeholder_input_raw: str = ""
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    advisor_consultations: list[dict[str, Any]] = field(default_factory=list)

    # ---- classification ---------------------------------------------------
    feature_type_confidence: float = 0.0   # 0.0–1.0

    # ---- core tier (weight=3) ---------------------------------------------
    feature_name: IntakeField = field(
        default_factory=lambda: IntakeField("feature_name", weight=3, tier="core")
    )
    feature_type: IntakeField = field(
        default_factory=lambda: IntakeField("feature_type", weight=3, tier="core")
    )
    problem_statement: IntakeField = field(
        default_factory=lambda: IntakeField("problem_statement", weight=3, tier="core")
    )
    business_objective: IntakeField = field(
        default_factory=lambda: IntakeField("business_objective", weight=3, tier="core")
    )

    # ---- context tier (weight=2) ------------------------------------------
    target_audience: IntakeField = field(
        default_factory=lambda: IntakeField("target_audience", weight=2, tier="context")
    )
    success_metrics: IntakeField = field(
        default_factory=lambda: IntakeField("success_metrics", weight=2, tier="context")
    )
    dependencies: IntakeField = field(
        default_factory=lambda: IntakeField("dependencies", weight=2, tier="context")
    )
    timeline_constraints: IntakeField = field(
        default_factory=lambda: IntakeField("timeline_constraints", weight=2, tier="context")
    )

    # ---- detail tier (weight=1) -------------------------------------------
    solution_approach: IntakeField = field(
        default_factory=lambda: IntakeField("solution_approach", weight=1, tier="detail")
    )
    scope_inclusions: IntakeField = field(
        default_factory=lambda: IntakeField("scope_inclusions", weight=1, tier="detail")
    )
    scope_exclusions: IntakeField = field(
        default_factory=lambda: IntakeField("scope_exclusions", weight=1, tier="detail")
    )
    additional_context: IntakeField = field(
        default_factory=lambda: IntakeField("additional_context", weight=1, tier="detail")
    )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _all_fields(self) -> list[IntakeField]:
        return [
            self.feature_name,
            self.feature_type,
            self.problem_statement,
            self.business_objective,
            self.target_audience,
            self.success_metrics,
            self.dependencies,
            self.timeline_constraints,
            self.solution_approach,
            self.scope_inclusions,
            self.scope_exclusions,
            self.additional_context,
        ]

    def readiness_score(self) -> int:
        """Weighted sum of populated fields."""
        return sum(f.weight for f in self._all_fields() if f.is_populated())

    def gap_inventory(self) -> dict[str, list[str]]:
        """Unpopulated fields grouped by tier."""
        gaps: dict[str, list[str]] = {"core": [], "context": [], "detail": []}
        for f in self._all_fields():
            if not f.is_populated():
                gaps[f.tier].append(f.name)
        return gaps

    def knowledge_boundary(self) -> list[str]:
        """Fields where the stakeholder explicitly said 'I don't know'."""
        return [f.name for f in self._all_fields() if f.status == FieldStatus.UNKNOWN]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict for database storage."""
        def _field_to_dict(f: IntakeField) -> dict[str, Any]:
            return {
                "name": f.name,
                "value": f.value,
                "status": f.status.value,
                "weight": f.weight,
                "tier": f.tier,
            }

        return {
            "stakeholder_input_raw": self.stakeholder_input_raw,
            "conversation_history": self.conversation_history,
            "advisor_consultations": self.advisor_consultations,
            "feature_type_confidence": self.feature_type_confidence,
            "feature_name": _field_to_dict(self.feature_name),
            "feature_type": _field_to_dict(self.feature_type),
            "problem_statement": _field_to_dict(self.problem_statement),
            "business_objective": _field_to_dict(self.business_objective),
            "target_audience": _field_to_dict(self.target_audience),
            "success_metrics": _field_to_dict(self.success_metrics),
            "dependencies": _field_to_dict(self.dependencies),
            "timeline_constraints": _field_to_dict(self.timeline_constraints),
            "solution_approach": _field_to_dict(self.solution_approach),
            "scope_inclusions": _field_to_dict(self.scope_inclusions),
            "scope_exclusions": _field_to_dict(self.scope_exclusions),
            "additional_context": _field_to_dict(self.additional_context),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeRecord":
        """Reconstruct an IntakeRecord from a serialized dict."""
        def _dict_to_field(d: dict[str, Any]) -> IntakeField:
            return IntakeField(
                name=d["name"],
                value=d.get("value"),
                status=FieldStatus(d["status"]),
                weight=d.get("weight", 1),
                tier=d.get("tier", "detail"),
            )

        record = cls(
            stakeholder_input_raw=data.get("stakeholder_input_raw", ""),
            conversation_history=data.get("conversation_history", []),
            advisor_consultations=data.get("advisor_consultations", []),
            feature_type_confidence=data.get("feature_type_confidence", 0.0),
        )
        for field_name in (
            "feature_name", "feature_type", "problem_statement", "business_objective",
            "target_audience", "success_metrics", "dependencies", "timeline_constraints",
            "solution_approach", "scope_inclusions", "scope_exclusions", "additional_context",
        ):
            if field_name in data:
                setattr(record, field_name, _dict_to_field(data[field_name]))
        return record

    def to_generator_input(self) -> dict[str, Any]:
        """
        Transform the record into the format expected by agents/generator.py:
        {
            "feature_type": str,
            "section_answers": {section_name: answer_text},
        }
        Unknown/unasked fields are represented as [NEEDS INPUT: <name>].
        """
        def _val(f: IntakeField) -> str:
            if f.is_populated() and f.value:
                return f.value
            if f.status == FieldStatus.UNKNOWN:
                return f"[NEEDS INPUT: stakeholder does not know — {f.name}]"
            return f"[NEEDS INPUT: {f.name}]"

        section_answers: dict[str, str] = {
            "Feature Overview": (
                f"Feature Name: {_val(self.feature_name)}\n"
                f"Feature Type: {_val(self.feature_type)}\n"
                f"Problem Statement: {_val(self.problem_statement)}\n"
                f"Business Objective: {_val(self.business_objective)}"
            ),
            "Audience & Metrics": (
                f"Target Audience: {_val(self.target_audience)}\n"
                f"Success Metrics: {_val(self.success_metrics)}"
            ),
            "Scope & Approach": (
                f"Solution Approach: {_val(self.solution_approach)}\n"
                f"In Scope: {_val(self.scope_inclusions)}\n"
                f"Out of Scope: {_val(self.scope_exclusions)}"
            ),
            "Dependencies & Constraints": (
                f"Dependencies: {_val(self.dependencies)}\n"
                f"Timeline Constraints: {_val(self.timeline_constraints)}"
            ),
            "Additional Context": _val(self.additional_context),
        }

        ft = self.feature_type.value or "UNKNOWN"
        return {
            "feature_type": ft.upper(),
            "section_answers": section_answers,
        }


# ---------------------------------------------------------------------------
# ReadinessScorer
# ---------------------------------------------------------------------------

_ACCEPT_THRESHOLD = 16
_CAVEATS_THRESHOLD = 10
_ADVISOR_CONFIDENCE_THRESHOLD = 0.7


class ReadinessScorer:

    def score(self, record: IntakeRecord) -> int:
        return record.readiness_score()

    def recommendation(self, record: IntakeRecord) -> dict[str, Any]:
        s = self.score(record)
        gaps_by_tier = record.gap_inventory()
        gaps_flat = (
            gaps_by_tier["core"]
            + gaps_by_tier["context"]
            + gaps_by_tier["detail"]
        )
        kb = record.knowledge_boundary()

        if s >= _ACCEPT_THRESHOLD:
            action = "accept"
            rationale = f"Readiness score {s} meets acceptance threshold ({_ACCEPT_THRESHOLD})."
        elif s >= _CAVEATS_THRESHOLD:
            action = "accept_with_caveats"
            rationale = (
                f"Readiness score {s} is sufficient but incomplete "
                f"(threshold {_CAVEATS_THRESHOLD}–{_ACCEPT_THRESHOLD - 1}). "
                "Generator will insert [NEEDS INPUT] placeholders."
            )
        else:
            action = "needs_more_input"
            rationale = (
                f"Readiness score {s} is below minimum threshold ({_CAVEATS_THRESHOLD}). "
                "Core information is missing."
            )

        return {
            "action": action,
            "rationale": rationale,
            "gaps": gaps_flat,
            "knowledge_boundary": kb,
        }

    @staticmethod
    def needs_advisor(record: IntakeRecord) -> bool:
        """True when feature-type confidence is below the advisor threshold."""
        return record.feature_type_confidence < _ADVISOR_CONFIDENCE_THRESHOLD


# ---------------------------------------------------------------------------
# ConversationManager
# ---------------------------------------------------------------------------

class ConversationState(Enum):
    GREETING = "greeting"
    INITIAL_PROCESSING = "initial_processing"
    ASKING_QUESTIONS = "asking_questions"
    SUMMARIZING = "summarizing"
    CONFIRMED = "confirmed"


_IDK_WRAP_UP_THRESHOLD = 3   # consecutive "I don't know" triggers early wrap-up


class ConversationManager:

    def __init__(self) -> None:
        self.state: ConversationState = ConversationState.GREETING
        self.asked_fields: set[str] = set()
        self.consecutive_idk_count: int = 0

    def record_answer(self, field_name: str, status: FieldStatus) -> None:
        self.asked_fields.add(field_name)

    def record_turn_idk(self) -> None:
        """Call once per turn when the stakeholder said 'I don't know'."""
        self.consecutive_idk_count += 1

    def record_turn_answered(self) -> None:
        """Call once per turn when the stakeholder gave a substantive answer."""
        self.consecutive_idk_count = 0

    def next_action(self, record: IntakeRecord) -> str:
        """
        Returns one of: "ask_core", "ask_context", "ask_detail", "summarize".

        Decision order:
        1. Too many consecutive IDKs → summarize early.
        2. Unpopulated core fields exist → ask_core.
        3. Score high enough to skip detail → summarize (caveats or accept).
        4. Unpopulated context fields exist → ask_context.
        5. Unpopulated detail fields exist → ask_detail.
        6. Nothing left → summarize.
        """
        if self.consecutive_idk_count >= _IDK_WRAP_UP_THRESHOLD:
            return "summarize"

        gaps = record.gap_inventory()

        unasked_core = [f for f in gaps["core"] if f not in self.asked_fields]
        if unasked_core:
            return "ask_core"

        scorer = ReadinessScorer()
        rec = scorer.recommendation(record)
        if rec["action"] in ("accept", "accept_with_caveats"):
            return "summarize"

        unasked_context = [f for f in gaps["context"] if f not in self.asked_fields]
        if unasked_context:
            return "ask_context"

        unasked_detail = [f for f in gaps["detail"] if f not in self.asked_fields]
        if unasked_detail:
            return "ask_detail"

        return "summarize"
