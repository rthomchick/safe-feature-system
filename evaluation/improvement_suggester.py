# evaluation/improvement_suggester.py
# ImprovementSuggester: analyzes stored eval runs for a golden-set case,
# identifies the weakest-scoring sections, and calls Claude Sonnet to propose
# specific edits to the generator system prompt.
#
# Advisory only — proposes changes, the PM decides whether to apply them.
#
# Typical usage:
#   from evaluation.improvement_suggester import ImprovementSuggester
#   suggester = ImprovementSuggester(store, registry, anthropic_client)
#   results   = suggester.suggest("cap_001_bare", n_sections=3)
#   for s in results:
#       print(s.section_name, s.avg_pct, s.suggested_edit)

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from evaluation.result_store import ResultStore
from evaluation.prompt_registry import PromptRegistry


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM = """\
You are a prompt engineer analyzing a generative AI pipeline to identify targeted \
improvements to a generator system prompt.

You will receive:
- A section name from a SAFe Feature spec quality rubric that has consistently scored low
- Aggregated reviewer feedback explaining what content was missing or weak
- The current generator system prompt

Your job: diagnose why the generator is underperforming on this section and propose \
a precise, concrete prompt edit. Generic advice ("be more detailed") is not acceptable.

Respond in exactly this format with all four numbered labels:

1. QUOTE:
[Quote the exact sentence(s) from the generator prompt that address this section. \
If no relevant guidance exists, write: No explicit guidance found for this section.]

2. DIAGNOSIS:
[2–3 sentences explaining what is underspecified in the current prompt that causes \
the generator to produce weak content for this section.]

3. SUGGESTED EDIT:
[The exact text to add to or replace in the generator prompt. \
Prefix additions with "+ " and removals with "- ". \
Be specific about where in the prompt this goes (e.g., "Add under REQUIRED CONTENT:").]

4. RATIONALE:
[1–2 sentences explaining why this specific change should raise scores on this section.]\
"""

_ANALYSIS_USER = """\
WEAK SECTION: {section_name}
Average score: {avg_pct:.0f}%  ({avg_score:.1f} / {avg_max:.1f} points)  across {n_runs} run(s)

REVIEWER FEEDBACK collected across all runs:
{aggregated_feedback}

CURRENT GENERATOR SYSTEM PROMPT:
---
{generator_prompt}
---

Analyze the weak "{section_name}" section and suggest a precise edit to the generator prompt.\
"""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SectionSuggestion:
    """Analysis result for one weak section."""
    section_name:         str
    avg_score:            float
    avg_max:              float
    avg_pct:              float        # 0–100
    n_runs:               int
    aggregated_feedback:  str          # deduplicated reviewer recommendations
    quote:                str = ""     # relevant quote from the current prompt
    diagnosis:            str = ""     # root-cause explanation
    suggested_edit:       str = ""     # exact edit text
    rationale:            str = ""     # why this edit should help
    raw_response:         str = ""     # full Claude response (fallback display)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name":        self.section_name,
            "avg_score":           self.avg_score,
            "avg_max":             self.avg_max,
            "avg_pct":             self.avg_pct,
            "n_runs":              self.n_runs,
            "aggregated_feedback": self.aggregated_feedback,
            "quote":               self.quote,
            "diagnosis":           self.diagnosis,
            "suggested_edit":      self.suggested_edit,
            "rationale":           self.rationale,
        }


# ---------------------------------------------------------------------------
# Suggester
# ---------------------------------------------------------------------------

class ImprovementSuggester:
    """Analyzes stored eval runs and suggests generator prompt improvements.

    Args:
        store:    ResultStore for reading eval run history.
        registry: PromptRegistry for retrieving the current generator prompt.
        client:   anthropic.Anthropic instance (must have a valid API key).
    """

    def __init__(
        self,
        store:    ResultStore,
        registry: PromptRegistry,
        client,
    ) -> None:
        self.store    = store
        self.registry = registry
        self.client   = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def suggest(
        self,
        golden_set_id: str,
        n_sections: int = 3,
    ) -> list[SectionSuggestion]:
        """Identify the n weakest sections and propose prompt edits.

        Steps:
          1. Load all stored runs for golden_set_id.
          2. Aggregate section scores and reviewer feedback across runs.
          3. Sort sections by average score % (ascending) and take the n lowest.
          4. Fetch the current generator prompt from the registry.
          5. For each weak section, call Claude Sonnet to produce a suggestion.

        Args:
            golden_set_id: Golden-set entry id (e.g. "cap_001_bare").
            n_sections:    Number of weak sections to analyze (default 3).

        Returns:
            List of SectionSuggestion, ordered weakest first.
            Empty list if no runs exist for this case.
        """
        runs = self.store.get_runs_for_golden(golden_set_id)
        if not runs:
            return []

        section_stats = self._aggregate_sections(runs)
        if not section_stats:
            return []

        ranked     = sorted(section_stats.values(), key=lambda s: s["avg_pct"])
        weak       = ranked[:n_sections]

        gen_row    = self.registry.get_latest("generator_v1")
        gen_prompt = gen_row["system_prompt"] if gen_row else "(generator prompt not found in registry)"

        return [self._analyze_section(stats, gen_prompt) for stats in weak]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _aggregate_sections(self, runs: list[dict]) -> dict[str, dict[str, Any]]:
        """Build per-section aggregates from all scorecard JSON blobs.

        Skips runs with parse errors. Deduplicates reviewer feedback strings.

        Returns:
            Dict[section_name, {avg_score, avg_max, avg_pct, n_runs, aggregated_feedback}]
        """
        accum: dict[str, dict[str, list]] = {}

        for run in runs:
            sc = run.get("scorecard") or {}
            if "parse_error" in sc:
                continue
            for sec_name, sec_data in sc.get("sections", {}).items():
                if sec_name not in accum:
                    accum[sec_name] = {"scores": [], "maxes": [], "feedbacks": []}
                accum[sec_name]["scores"].append(sec_data.get("score", 0))
                accum[sec_name]["maxes"].append(sec_data.get("max_points", 0))
                rec = (sec_data.get("recommendations") or "").strip()
                if rec:
                    accum[sec_name]["feedbacks"].append(rec)

        result: dict[str, dict[str, Any]] = {}
        for sec_name, data in accum.items():
            n     = len(data["scores"])
            avg_s = sum(data["scores"]) / n
            avg_m = sum(data["maxes"])  / n if data["maxes"] else 0
            avg_pct = round(avg_s / avg_m * 100, 1) if avg_m > 0 else 0.0

            # Deduplicate feedback while preserving order
            seen: set[str] = set()
            unique_fb: list[str] = []
            for fb in data["feedbacks"]:
                if fb not in seen:
                    seen.add(fb)
                    unique_fb.append(fb)

            feedback = "\n\n".join(unique_fb) if unique_fb else (
                "(No recommendations recorded — section may have scored ≥75% in all runs.)"
            )

            result[sec_name] = {
                "section_name":        sec_name,
                "avg_score":           round(avg_s, 1),
                "avg_max":             round(avg_m, 1),
                "avg_pct":             avg_pct,
                "n_runs":              n,
                "aggregated_feedback": feedback,
            }

        return result

    def _analyze_section(
        self,
        stats: dict[str, Any],
        generator_prompt: str,
    ) -> SectionSuggestion:
        """Call Claude Sonnet to generate a prompt-improvement suggestion."""
        user_msg = _ANALYSIS_USER.format(
            section_name=stats["section_name"],
            avg_pct=stats["avg_pct"],
            avg_score=stats["avg_score"],
            avg_max=stats["avg_max"],
            n_runs=stats["n_runs"],
            aggregated_feedback=stats["aggregated_feedback"],
            generator_prompt=generator_prompt,
        )

        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            temperature=0.2,
            system=_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()

        parsed = _parse_numbered_response(raw)

        return SectionSuggestion(
            section_name=stats["section_name"],
            avg_score=stats["avg_score"],
            avg_max=stats["avg_max"],
            avg_pct=stats["avg_pct"],
            n_runs=stats["n_runs"],
            aggregated_feedback=stats["aggregated_feedback"],
            raw_response=raw,
            **parsed,
        )


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_numbered_response(text: str) -> dict[str, str]:
    """Extract QUOTE / DIAGNOSIS / SUGGESTED EDIT / RATIONALE from Claude's response.

    Works line-by-line so it handles variations in whitespace and capitalisation.
    Falls back gracefully: any unparsed sections remain as empty strings.
    """
    result: dict[str, str] = {
        "quote":          "",
        "diagnosis":      "",
        "suggested_edit": "",
        "rationale":      "",
    }

    _KEY_MAP: dict[str, str] = {
        "quote":          "quote",
        "diagnosis":      "diagnosis",
        "suggested edit": "suggested_edit",
        "rationale":      "rationale",
    }

    current_key: str | None = None
    buffer: list[str]       = []

    for line in text.split("\n"):
        stripped = line.strip()

        # Match "1. QUOTE:", "3. SUGGESTED EDIT:", etc. at the start of a line
        m = re.match(r"^\d+\.\s+([A-Z][A-Z\s]+?)\s*:", stripped, re.IGNORECASE)
        if m:
            # Flush previous section into result
            if current_key:
                result[current_key] = "\n".join(buffer).strip()
                buffer = []

            label = m.group(1).strip().lower()
            current_key = _KEY_MAP.get(label)

            # Anything after the colon on the same line belongs to the section
            after_colon = stripped[m.end():].strip()
            if after_colon:
                buffer.append(after_colon)
        elif current_key is not None:
            buffer.append(line)

    # Flush the final section
    if current_key:
        result[current_key] = "\n".join(buffer).strip()

    return result
