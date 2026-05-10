# agents/reviewer.py
# agents/reviewer.py
import anthropic
import os
import json
from prompts.reviewer import RUBRIC

try:
    import streamlit as st
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=api_key)

from evaluation.token_tracker import llm_call, llm_call_with_advisor

REVIEWER_SYSTEM_PROMPT = """You are a SAFe Feature specification reviewer at ServiceNow. \
You score feature specs against a 100-point rubric and return structured JSON.

You will receive a SAFe Feature specification and a scoring rubric. For each criterion:
- Read the spec carefully for evidence of that criterion
- Award points based on how completely and specifically the criterion is met
- Write a brief recommendation only for criteria scoring below 75% of their maximum

Return ONLY valid JSON. No preamble, no explanation, no markdown code fences.
Return exactly this structure:

{
  "total_score": <integer 0-100>,
  "sections": {
    "<section_name>": {
      "max_points": <integer>,
      "score": <integer>,
      "criteria": {
        "<criterion_name>": {
          "max": <integer>,
          "score": <integer>,
          "note": "<brief note if score < 75% of max, else empty string>"
        }
      },
      "recommendations": "<combined recommendations for weak criteria in this section, else empty string>"
    }
  }
}"""


# ---------------------------------------------------------------------------
# Feature-type-aware scoring guidance
# ---------------------------------------------------------------------------
# The rubric is universal (100 points, same sections for all types).
# These interpretation blocks tell the Reviewer how to adapt its expectations
# for sections that differ by feature type — without changing the rubric itself.

FEATURE_TYPE_GUIDANCE = {
    "CAPABILITY": """
FEATURE TYPE CONTEXT: This is a CAPABILITY — a backend system, engine, API, \
or integration with no user-facing page or UI component.

Adapt your scoring for these sections:
- SEO, SEM, Analytics: There is no page to optimize for search. Award full marks \
  for SEO Strategy and SEM if the spec explains why SEO is not applicable AND \
  provides equivalent analytics coverage (event tracking, CDP integration, KPI \
  dashboards, data pipeline monitoring). Do not penalize for missing keywords, \
  meta tags, or page-level SEO.
- Campaigns: There is no campaign landing page. Award full marks for Campaign \
  Integration and Attribution if the spec explains how the capability enables or \
  feeds downstream campaigns (e.g., audience segmentation, lead enrichment, \
  personalization targeting). Do not penalize for missing landing page specs, \
  paid campaign details, or email campaign templates.
- Studio, Design & Accessibility: There may be no UI to design. Award full marks \
  for Design Standards, Media & Interactivity, and Accessibility if the spec \
  explains why design is not applicable AND provides equivalent concerns \
  (API performance targets, system integration requirements, data schema design). \
  Do not penalize for missing wireframes, visual specs, or WCAG details when \
  the feature is headless.
- Engineering, Publishing, QA & Content Model: For a capability, "publishing" \
  means deployment, not content publishing. Score Content Model based on data \
  schema quality (field types, sources, destinations) rather than CMS components. \
  QA requirements should focus on system testing, not visual QA.

All other sections: score normally using the standard rubric criteria.""",

    "EXPERIENCE": """
FEATURE TYPE CONTEXT: This is an EXPERIENCE — a UI component or interactive \
frontend feature that users directly see and interact with.

Adapt your scoring for these sections:
- SEO, SEM, Analytics: The component itself may not have page-level SEO, but it \
  should have analytics tracking (interaction events, engagement metrics). Award \
  SEO Strategy marks based on whether the component supports the host page's SEO \
  (schema markup, accessibility for crawlers). Do not require standalone keywords \
  or meta tags for a component.
- Campaigns: A component may not have its own campaign. Award marks based on \
  whether the component integrates with campaign-driven pages or personalization \
  systems (e.g., Adobe Target variants, A/B testing hooks).

All other sections: score normally using the standard rubric criteria.""",

    "WEBPAGE": """
FEATURE TYPE CONTEXT: This is a WEBPAGE — a new page or update to an existing \
page on servicenow.com where the primary work is content, messaging, SEO, and \
the publishing workflow.

All rubric sections apply directly. Score using the standard criteria without \
adaptation. Webpages should demonstrate strong SEO strategy, campaign integration, \
design specifications, and content model detail.""",
}


def _get_type_guidance(feature_type: str | None) -> str:
    """Return the scoring interpretation block for a feature type, or empty string."""
    if not feature_type:
        return ""
    return FEATURE_TYPE_GUIDANCE.get(feature_type.upper(), "")


def _build_rubric_text() -> str:
    """Convert the rubric dict into a readable prompt section."""
    parts = []
    for section_name, section_data in RUBRIC.items():
        parts.append(f"\n{section_name} (max {section_data['max_points']} points)")
        for criterion in section_data["criteria"]:
            parts.append(
                f"  - {criterion['name']} (max {criterion['max']} pts): {criterion['guidance']}"
            )
    return "\n".join(parts)


def review_feature_spec(spec: str, feature_type: str = None, tracker=None, use_advisor: bool = False) -> dict:
    """
    Score a SAFe Feature spec against the 100-point rubric.

    Args:
        spec:         The full SAFe Feature specification text
        feature_type: Optional — CAPABILITY, EXPERIENCE, or WEBPAGE.
                      When provided, the Reviewer adapts its scoring expectations
                      for sections that differ by type (e.g., SEO for a backend
                      capability vs. a webpage).

    Returns:
        Dict with total_score, per-section scores, per-criterion scores,
        and recommendations for weak sections
    """
    rubric_text = _build_rubric_text()
    type_guidance = _get_type_guidance(feature_type)

    prompt = f"""Please score this SAFe Feature specification against the rubric below.
{type_guidance}
RUBRIC:
{rubric_text}

SPECIFICATION TO SCORE:
{spec}

Return your scores as JSON only."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    raw = call_fn(
        client, tracker, "reviewer",
        model="claude-sonnet-4-6",
        max_tokens=9000,
        temperature=0.0,
        system=REVIEWER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    ).strip()

    # Strip markdown fences if Claude adds them despite instructions
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # Return a safe fallback so the pipeline doesn't crash
        return {
            "total_score": 0,
            "parse_error": str(e),
            "raw_response": raw,
            "sections": {}
        }


def _build_section_rubric_text(rubric_section_names: list[str]) -> str:
    """
    Build rubric text for ONLY the specified sections.
    rubric_section_names should be the Reviewer's output format (no Roman numerals).
    We match them against RUBRIC keys by stripping the Roman numeral prefix.
    """
    # Build a lookup: stripped name → full RUBRIC key
    stripped_to_key = {}
    for key in RUBRIC:
        # Strip "I. ", "II. ", "III. ", etc.
        stripped = key.split(". ", 1)[1] if ". " in key else key
        stripped_to_key[stripped] = key

    parts = []
    for name in rubric_section_names:
        rubric_key = stripped_to_key.get(name)
        if not rubric_key:
            continue
        section_data = RUBRIC[rubric_key]
        parts.append(f"\n{name} (max {section_data['max_points']} points)")
        for criterion in section_data["criteria"]:
            parts.append(
                f"  - {criterion['name']} (max {criterion['max']} pts): "
                f"{criterion['guidance']}"
            )
    return "\n".join(parts)


def review_sections(spec: str, section_names: list[str], feature_type: str = None, tracker=None, use_advisor: bool = False) -> dict:
    """
    Score ONLY the specified rubric sections of a spec, in isolation.

    This prevents score drift: when the Reviewer evaluates the full spec,
    improving section A can cause it to re-score section B differently
    even if B's text hasn't changed. By evaluating only the sections
    that were actually modified, untouched sections keep their original scores.

    Args:
        spec:           The full SAFe Feature specification text
        section_names:  List of rubric section names to score (Reviewer format,
                        no Roman numerals — e.g. "SEO, SEM, Analytics")
        feature_type:   Optional — CAPABILITY, EXPERIENCE, or WEBPAGE

    Returns:
        Dict with the same structure as review_feature_spec(), but only
        containing the requested sections. total_score is the sum of
        only the scored sections (not the full 100-point total).
    """
    rubric_text = _build_section_rubric_text(section_names)

    if not rubric_text.strip():
        return {"total_score": 0, "sections": {}}

    section_list = ", ".join(section_names)
    type_guidance = _get_type_guidance(feature_type)

    prompt = f"""Please score ONLY these sections of the SAFe Feature specification:
{section_list}

Ignore all other sections — do not score them, do not include them in your response.
{type_guidance}
RUBRIC (only the sections to score):
{rubric_text}

SPECIFICATION:
{spec}

Return your scores as JSON only. Include only the sections listed above."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    raw = call_fn(
        client, tracker, "reviewer",
        model="claude-sonnet-4-6",
        max_tokens=4000,
        temperature=0.0,
        system=REVIEWER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    ).strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        return {
            "total_score": 0,
            "parse_error": str(e),
            "raw_response": raw,
            "sections": {}
        }