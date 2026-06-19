# agents/improver.py
#
# Architecture: PARSE → EDIT → REASSEMBLE
#
# The spec is split into discrete sections by ## headings ONCE at the start.
# Each section is edited independently — no section edit can affect any other.
# Sections not targeted for improvement pass through as the original string.
# Finally, all sections are reassembled in their original order.
#
# This eliminates the entire class of splice/boundary bugs from the previous
# approach where positional string surgery meant every edit could structurally
# corrupt downstream sections.

import anthropic
import re

try:
    import streamlit as st
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=api_key)

from evaluation.token_tracker import llm_call, llm_call_with_advisor


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

# Standard path: returns the complete section with targeted edits
IMPROVER_SYSTEM_PROMPT = """You are a precise SAFe Feature specification editor at ServiceNow. \
You make targeted additions and corrections to specific sections — you do not rewrite.

You will receive:
1. A section from a SAFe Feature specification
2. A list of specific criteria that scored below their maximum — these are the ONLY things to fix
3. Optional: additional context provided by the PM

Your rules:
- Address ONLY the specific failing criteria listed — nothing else
- Preserve all existing content that isn't directly related to a failing criterion
- Add missing content rather than replacing existing content wherever possible
- If a criterion requires new content (e.g. a missing traceability matrix), append it
- If a criterion requires correcting something that exists, make the minimal edit needed
- Do not change the section's structure, tone, voice, or any content not related to the failing criteria
- Return the complete section with only the targeted changes applied
- Your output must start with the same ## heading as the input section"""

# Append-only path: model returns ONLY new content in XML tags.
# Python handles concatenation. Model never reproduces existing content.
APPEND_ONLY_SYSTEM_PROMPT = """You are a precise SAFe Feature specification editor at ServiceNow.

CRITICAL CONSTRAINT: You must NEVER reproduce, rewrite, or paraphrase any existing \
user stories, acceptance criteria, priority assignments, or business rationale. \
The existing content is FROZEN and will be preserved by the system automatically.

You will receive:
1. A section from a SAFe Feature specification (for context only — do NOT reproduce it)
2. A list of specific criteria that scored below their maximum

Your job is to return ONLY the new content that needs to be added, using this exact format:

<additions>
<addition placement="append_after_stories" label="[descriptive label]">
[New content to append after all existing user stories — e.g., a traceability matrix, \
effort estimates table, or new user stories that are missing]
</addition>
</additions>

<modifications>
<modification target="[identify the specific element to modify]" action="[insert_after|add_column|add_row]">
[The specific new content to insert. Describe WHERE it goes relative to the existing content.]
</modification>
</modifications>

Rules:
- Return ONLY <additions> and/or <modifications> blocks — nothing else
- If no additions are needed, return an empty <additions></additions> block
- If no modifications are needed, return an empty <modifications></modifications> block
- NEVER include the original section content in your response
- Each <addition> should be self-contained content ready to append
- Each <modification> must identify its target precisely (e.g., "User Story 3" or "all stories")
- For effort estimates: produce a summary table to append, do NOT try to edit each story inline
- For traceability: produce a matrix to append, do NOT try to edit each story inline
- Prefer appending new subsections over modifying existing content"""

# Addendum path: generates entirely new ## blocks for sections not found in the spec
ADDENDUM_SYSTEM_PROMPT = """You are a SAFe Feature specification writer at ServiceNow. \
You write new sections for feature specs that are entirely missing required content.

You will receive:
1. A complete SAFe Feature specification for context
2. A list of sections that are missing, with specific failing criteria and reviewer recommendations
3. Optional: additional context provided by the PM for specific sections

Your job:
- Write each missing section as a new ## heading block
- For each section, address only the specific failing criteria listed
- Use context from the existing spec to make content specific and relevant
- If PM context is provided for a section, incorporate it directly
- Be specific — use system names, team names, and details already present in the spec
- Format each section with a ## heading matching the section name
- Return all missing sections concatenated together, each with its ## heading"""


# ---------------------------------------------------------------------------
# Spec parser: split into discrete sections by ## headings
# ---------------------------------------------------------------------------

def _split_spec_into_sections(spec: str) -> tuple[str, list[dict]]:
    """
    Split a markdown spec into a preamble (content before the first ## heading)
    and a list of discrete sections, each identified by its ## heading.

    Returns:
        (preamble, sections) where sections is a list of dicts:
        [
            {
                "heading": "## Feature Title",
                "body": "content after heading...",
                "full_text": "## Feature Title\ncontent after heading..."
            },
            ...
        ]

    Each section's full_text is a self-contained block that can be edited
    independently and reassembled without affecting other sections.
    """
    # Find all ## heading positions (but not ### or deeper)
    heading_pattern = re.compile(r'^(## [^\n]+)', re.MULTILINE)
    matches = list(heading_pattern.finditer(spec))

    if not matches:
        return spec, []

    preamble = spec[:matches[0].start()]

    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(spec)

        full_text = spec[start:end].rstrip()
        heading = match.group(1).strip()
        body = spec[match.end():end].strip()

        sections.append({
            "heading": heading,
            "body": body,
            "full_text": full_text,
        })

    return preamble, sections


def _reassemble_spec(preamble: str, sections: list[dict]) -> str:
    """
    Reassemble a spec from its preamble and list of sections.
    Each section's full_text is used as-is.
    """
    parts = [preamble.rstrip()]
    for section in sections:
        parts.append(section["full_text"])
    return "\n\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Rubric name ↔ heading mapping
# ---------------------------------------------------------------------------

RUBRIC_TO_HEADINGS = {
    "Feature Definition & Objective": [
        "Feature Title", "Description", "Objective",
    ],
    "Content Strategy & Value Proposition": [
        "Solution Approach", "Value Proposition", "Content Strategy",
    ],
    "Scope, Out of Scope, and Dependencies": [
        "Scope (In-Scope)", "Scope", "Out of Scope", "Dependencies",
    ],
    "Studio, Design & Accessibility": [
        "Design & Accessibility", "Design", "Studio", "Accessibility",
    ],
    "Copywriting, Messaging & Compliance": [
        "Copywriting & Messaging", "Copywriting", "Messaging",
    ],
    "SEO, SEM, Analytics": [
        "SEO & Analytics", "SEO", "Analytics",
    ],
    "Campaigns": [
        "Campaign Integration", "Campaign", "Campaigns",
    ],
    "Engineering, Publishing, QA & Content Model": [
        "Engineering & Publishing", "Engineering", "Publishing", "Technical",
    ],
    "User Stories & Acceptance Criteria": [
        "Acceptance Criteria", "User Stories",
    ],
}


def _heading_matches_rubric(heading: str, rubric_name: str) -> bool:
    """
    Check if a ## heading from the spec belongs to a rubric section.
    heading is the full "## Foo" string; we strip "## " before comparing.
    """
    clean_heading = heading.lstrip("#").strip().lower()
    candidates = RUBRIC_TO_HEADINGS.get(rubric_name, [rubric_name])
    return any(clean_heading == c.lower() for c in candidates)


def _find_sections_for_rubric(sections: list[dict], rubric_name: str) -> list[int]:
    """
    Return indices of all parsed sections that belong to a rubric section.
    A rubric section like "Feature Definition & Objective" might span multiple
    ## headings (## Feature Title, ## Description, ## Objective).
    """
    return [
        i for i, sec in enumerate(sections)
        if _heading_matches_rubric(sec["heading"], rubric_name)
    ]


# ---------------------------------------------------------------------------
# Criterion extraction
# ---------------------------------------------------------------------------

def _get_failing_criteria(section_data: dict) -> list[dict]:
    """
    Extract criteria that scored below their maximum from a section's scorecard data.
    Returns only criteria with a reviewer note — these are the specific gaps to fix.
    """
    failing = []
    for criterion_name, criterion_data in section_data.get("criteria", {}).items():
        max_pts = criterion_data.get("max", 0)
        score = criterion_data.get("score", 0)
        note = criterion_data.get("note", "")
        if max_pts > 0 and score < max_pts and note and note.strip():
            failing.append({
                "name": criterion_name,
                "score": score,
                "max": max_pts,
                "note": note.strip()
            })
    return failing


# ---------------------------------------------------------------------------
# Sections that use append-only editing
# ---------------------------------------------------------------------------

APPEND_ONLY_SECTIONS = {
    "User Stories & Acceptance Criteria",
}


# ---------------------------------------------------------------------------
# Append-only improvement (User Stories & Acceptance Criteria)
# ---------------------------------------------------------------------------

def _append_only_improve(
    section_content: str,
    section_name: str,
    failing_criteria: list[dict],
    additional_context: str = "",
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Improvement path for structured sections (User Stories) where existing
    content must be preserved verbatim. The LLM returns ONLY new content
    in XML tags. Python handles concatenation.

    Returns: the original section content + appended additions.
    """
    if not failing_criteria:
        return section_content

    criteria_lines = "\n".join(
        f"- {c['name']} ({c['score']}/{c['max']} pts): {c['note']}"
        for c in failing_criteria
    )

    context_block = ""
    if additional_context and additional_context.strip():
        context_block = f"""
The PM has provided the following additional context:
---
{additional_context.strip()}
---
Incorporate this where relevant to the failing criteria above.
"""

    prompt = f"""Section: {section_name}

The following existing content is FROZEN — do NOT reproduce or rewrite any of it:
---
{section_content}
---

These specific criteria scored below their maximum and need to be addressed:
{criteria_lines}
{context_block}
Return ONLY <additions> and <modifications> blocks. Do NOT return the existing content."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    llm_output = call_fn(
        client, tracker, "improver",
        model="claude-sonnet-4-6",
        max_tokens=2000,
        temperature=0.2,
        system=APPEND_ONLY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    # --- Parse additions ---
    additions = []
    for match in re.finditer(
        r'<addition[^>]*>(.*?)</addition>', llm_output, re.DOTALL
    ):
        content = match.group(1).strip()
        if content:
            additions.append(content)

    # --- Parse modifications (applied conservatively as appended subsection) ---
    modifications = []
    for match in re.finditer(
        r'<modification[^>]*>(.*?)</modification>', llm_output, re.DOTALL
    ):
        content = match.group(1).strip()
        if content:
            modifications.append(content)

    # --- Assemble: original content + additions ---
    result = section_content.rstrip()

    if additions:
        result += "\n\n"
        result += "\n\n".join(additions)

    if modifications:
        result += "\n\n### Reviewer-Requested Adjustments\n\n"
        result += "\n\n".join(modifications)

    return result


# ---------------------------------------------------------------------------
# Standard improvement (all other sections)
# ---------------------------------------------------------------------------

def _standard_improve(
    section_content: str,
    section_name: str,
    failing_criteria: list[dict],
    additional_context: str = "",
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Standard improvement path for sections where regeneration is acceptable.
    The LLM returns the complete section with targeted edits.
    """
    if not failing_criteria:
        return section_content

    criteria_lines = "\n".join(
        f"- {c['name']} ({c['score']}/{c['max']} pts): {c['note']}"
        for c in failing_criteria
    )

    context_block = ""
    if additional_context and additional_context.strip():
        context_block = f"""
The PM has provided the following additional context:
---
{additional_context.strip()}
---
Incorporate this where relevant to the failing criteria above.
"""

    prompt = f"""Section: {section_name}

Current content:
{section_content}

These specific criteria scored below their maximum and need to be addressed:
{criteria_lines}
{context_block}
Make only the targeted additions or corrections needed for these criteria. \
Preserve all other content exactly as written. \
Start your output with the same ## heading as the input section."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    return call_fn(
        client, tracker, "improver",
        model="claude-sonnet-4-6",
        max_tokens=2000,
        temperature=0.3,
        system=IMPROVER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )


# ---------------------------------------------------------------------------
# Section router
# ---------------------------------------------------------------------------

def _improve_single_section(
    section_content: str,
    section_name: str,
    failing_criteria: list[dict],
    additional_context: str = "",
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Route to the appropriate improvement strategy based on section name.
    """
    if section_name in APPEND_ONLY_SECTIONS:
        return _append_only_improve(
            section_content=section_content,
            section_name=section_name,
            failing_criteria=failing_criteria,
            additional_context=additional_context,
            tracker=tracker,
            use_advisor=use_advisor,
        )
    else:
        return _standard_improve(
            section_content=section_content,
            section_name=section_name,
            failing_criteria=failing_criteria,
            additional_context=additional_context,
            tracker=tracker,
            use_advisor=use_advisor,
        )


# ---------------------------------------------------------------------------
# Addendum generation (missing sections with no heading match)
# ---------------------------------------------------------------------------

def _generate_addendum(
    spec: str,
    missing_sections: list[dict],
    additional_context: dict = None,
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Generate new ## heading blocks for sections that don't exist in the spec at all.
    """
    if additional_context is None:
        additional_context = {}

    sections_brief = []
    for ws in missing_sections:
        section_name = ws["rubric_name"]
        extra = additional_context.get(section_name, "")

        criteria_lines = "\n".join(
            f"  - {c['name']} ({c['score']}/{c['max']} pts): {c['note']}"
            for c in ws.get("failing_criteria", [])
        )
        if not criteria_lines:
            criteria_lines = f"  - General: {ws.get('recommendations', 'Improve this section')}"

        entry = (
            f"**{section_name}** (scored {ws['score']} = {ws['pct']}%)\n"
            f"Failing criteria:\n{criteria_lines}"
        )
        if extra.strip():
            entry += f"\nPM context: {extra.strip()}"
        sections_brief.append(entry)

    sections_text = "\n\n".join(sections_brief)

    prompt = f"""Here is the existing SAFe Feature specification for context:

{spec}

---

The following sections are missing from the spec and need to be written. \
Address only the specific failing criteria listed for each section.

{sections_text}

Write each missing section as a ## heading block. Use details from the existing \
spec to make the content specific and relevant. Return all sections together."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    return call_fn(
        client, tracker, "improver",
        model="claude-sonnet-4-6",
        max_tokens=3000,
        temperature=0.3,
        system=ADDENDUM_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def improve_spec(
    spec: str,
    scorecard: dict,
    additional_context: dict = None,
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Improve weak sections of a spec using the PARSE → EDIT → REASSEMBLE pattern.

    1. PARSE:      Split spec into discrete sections by ## headings
    2. IDENTIFY:   Find rubric sections below 70% with failing criteria
    3. EDIT:       Improve each weak section independently (append-only or standard)
    4. REASSEMBLE: Concatenate all sections in original order

    No section edit can structurally affect any other section.

    Debug metadata is stored on improve_spec.last_debug after each call.
    Use this in stage_improve() to confirm exactly what was targeted:

        result = improve_spec(spec, scorecard, context)
        st.write("DEBUG improve_spec:", improve_spec.last_debug)
    """
    if additional_context is None:
        additional_context = {}

    # --- PARSE ---
    preamble, sections = _split_spec_into_sections(spec)

    # --- IDENTIFY weak rubric sections ---
    weak_rubric_sections = []
    skipped_above_threshold = []

    for section_name, data in scorecard.get("sections", {}).items():
        max_pts = data.get("max_points", 0)
        score = data.get("score", 0)
        pct = score / max_pts if max_pts > 0 else 0
        recommendations = data.get("recommendations", "")
        failing_criteria = _get_failing_criteria(data)

        if max_pts > 0 and pct <= 0.75 and (failing_criteria or recommendations):
            if not failing_criteria and recommendations:
                failing_criteria = [{
                    "name": "General improvements",
                    "score": 0,
                    "max": 1,
                    "note": recommendations
                }]

            weak_rubric_sections.append({
                "rubric_name": section_name,
                "score": score,
                "max_points": max_pts,
                "pct": f"{pct:.0%}",
                "recommendations": recommendations,
                "failing_criteria": failing_criteria,
            })
        else:
            skipped_above_threshold.append(f"{section_name}: {score}/{max_pts} ({pct:.0%})")

    # --- Debug metadata ---
    debug = {
        "parsed_headings": [s["heading"] for s in sections],
        "weak_rubric_sections": [w["rubric_name"] for w in weak_rubric_sections],
        "skipped_above_threshold": skipped_above_threshold,
        "all_scores": {
            name: f"{data.get('score', 0)}/{data.get('max_points', 0)} "
                  f"({data.get('score', 0)/max(data.get('max_points', 1), 1):.0%})"
            for name, data in scorecard.get("sections", {}).items()
        },
        "matched_in_place": [],
        "sent_to_addendum": [],
    }

    if not weak_rubric_sections:
        improve_spec.last_debug = debug
        return spec

    # --- EDIT each weak section independently ---
    addendum_sections = []

    for ws in weak_rubric_sections:
        rubric_name = ws["rubric_name"]
        failing_criteria = ws["failing_criteria"]
        extra = additional_context.get(rubric_name, "")

        # Find which parsed section(s) belong to this rubric section
        matching_indices = _find_sections_for_rubric(sections, rubric_name)

        if not matching_indices:
            addendum_sections.append(ws)
            debug["sent_to_addendum"].append(rubric_name)
            continue

        debug["matched_in_place"].append(
            f"{rubric_name} → headings: {[sections[i]['heading'] for i in matching_indices]}"
        )

        # Combine all matching ## headings into one block for the LLM
        # (e.g., "Feature Definition" might span ## Feature Title + ## Description)
        combined_content = "\n\n".join(
            sections[i]["full_text"] for i in matching_indices
        )

        # Run the appropriate improvement strategy
        improved_content = _improve_single_section(
            section_content=combined_content,
            section_name=rubric_name,
            failing_criteria=failing_criteria,
            additional_context=extra,
            tracker=tracker,
            use_advisor=use_advisor,
        )

        # Place improved content at the position of the first matching heading.
        # If rubric section spanned multiple ## headings, mark extras for removal.
        first_idx = matching_indices[0]
        sections[first_idx]["full_text"] = improved_content

        for idx in matching_indices[1:]:
            sections[idx]["full_text"] = None  # sentinel for removal

    # Remove sections that were folded into a multi-heading rubric section
    sections = [s for s in sections if s["full_text"] is not None]

    # --- REASSEMBLE ---
    improved_spec = _reassemble_spec(preamble, sections)

    # --- ADDENDUM for sections with no matching heading ---
    if addendum_sections:
        addendum = _generate_addendum(
            spec=improved_spec,
            missing_sections=addendum_sections,
            additional_context=additional_context,
            tracker=tracker,
            use_advisor=use_advisor,
        )
        improved_spec = improved_spec.rstrip() + "\n\n---\n\n" + addendum

    improve_spec.last_debug = debug
    return improved_spec


# Initialize debug attribute
improve_spec.last_debug = {}


# ---------------------------------------------------------------------------
# POLISH: lighter-touch pass for sections scoring 75-89%
# ---------------------------------------------------------------------------

POLISH_SYSTEM_PROMPT = """You are a precise SAFe Feature specification editor at ServiceNow.

This section already scores well (75%+). You are making minor additions to close \
the remaining gaps and reach full marks. The existing content is strong — your job \
is to add what's missing, not to rewrite what's there.

CRITICAL CONSTRAINT: You must NEVER reproduce, rewrite, or paraphrase existing content. \
The existing content is FROZEN and will be preserved by the system automatically.

You will receive:
1. A section from a SAFe Feature specification (for context only — do NOT reproduce it)
2. A list of specific criteria that scored below their maximum — minor gaps to close

Return ONLY the new content to add, using this exact format:

<additions>
<addition placement="append" label="[descriptive label]">
[New content to append — e.g., a missing stakeholder list, a performance target, \
a localization note, an additional proof point]
</addition>
</additions>

<modifications>
<modification target="[specific element]" action="[insert_after|add_detail]">
[Describe a specific small change. Keep it to one sentence or one data point.]
</modification>
</modifications>

Rules:
- Return ONLY <additions> and/or <modifications> blocks
- If no additions are needed, return empty <additions></additions>
- If no modifications are needed, return empty <modifications></modifications>
- NEVER reproduce existing content
- Keep additions concise — these are minor gap-fills, not new subsections
- Prefer one targeted addition over multiple small ones"""


def polish_spec(
    spec: str,
    scorecard: dict,
    additional_context: dict = None,
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Polish pass for sections scoring 75-89%. Uses append-only strategy for
    ALL sections to prevent regeneration damage to already-good content.

    Same PARSE → EDIT → REASSEMBLE architecture as improve_spec().

    Debug metadata stored on polish_spec.last_debug.
    """
    if additional_context is None:
        additional_context = {}

    preamble, sections = _split_spec_into_sections(spec)

    # --- IDENTIFY polish candidates: 75% <= score < 90% with failing criteria ---
    polish_candidates = []
    skipped = []

    for section_name, data in scorecard.get("sections", {}).items():
        max_pts = data.get("max_points", 0)
        score = data.get("score", 0)
        pct = score / max_pts if max_pts > 0 else 0
        failing_criteria = _get_failing_criteria(data)

        if max_pts > 0 and 0.80 <= pct < 0.90 and failing_criteria:
            polish_candidates.append({
                "rubric_name": section_name,
                "score": score,
                "max_points": max_pts,
                "pct": f"{pct:.0%}",
                "failing_criteria": failing_criteria,
            })
        else:
            skipped.append(f"{section_name}: {score}/{max_pts} ({pct:.0%})")

    debug = {
        "polish_candidates": [p["rubric_name"] for p in polish_candidates],
        "skipped": skipped,
        "matched_in_place": [],
    }

    if not polish_candidates:
        polish_spec.last_debug = debug
        return spec

    # --- EDIT each polish candidate with append-only strategy ---
    for pc in polish_candidates:
        rubric_name = pc["rubric_name"]
        failing_criteria = pc["failing_criteria"]
        extra = additional_context.get(rubric_name, "")

        matching_indices = _find_sections_for_rubric(sections, rubric_name)

        if not matching_indices:
            continue

        debug["matched_in_place"].append(rubric_name)

        combined_content = "\n\n".join(
            sections[i]["full_text"] for i in matching_indices
        )

        # ALL polish sections use append-only — these are already-good sections
        improved_content = _polish_single_section(
            section_content=combined_content,
            section_name=rubric_name,
            failing_criteria=failing_criteria,
            additional_context=extra,
            tracker=tracker,
            use_advisor=use_advisor,
        )

        first_idx = matching_indices[0]
        sections[first_idx]["full_text"] = improved_content

        for idx in matching_indices[1:]:
            sections[idx]["full_text"] = None

    sections = [s for s in sections if s["full_text"] is not None]

    polished_spec = _reassemble_spec(preamble, sections)

    polish_spec.last_debug = debug
    return polished_spec


polish_spec.last_debug = {}


def _polish_single_section(
    section_content: str,
    section_name: str,
    failing_criteria: list[dict],
    additional_context: str = "",
    tracker=None,
    use_advisor: bool = False,
) -> str:
    """
    Append-only polish for a section scoring 75-89%.
    Uses POLISH_SYSTEM_PROMPT — lighter touch than the Improver.
    Returns original content + appended additions.
    """
    if not failing_criteria:
        return section_content

    criteria_lines = "\n".join(
        f"- {c['name']} ({c['score']}/{c['max']} pts): {c['note']}"
        for c in failing_criteria
    )

    context_block = ""
    if additional_context and additional_context.strip():
        context_block = f"""
The PM has provided additional context:
---
{additional_context.strip()}
---
"""

    prompt = f"""Section: {section_name}

The following existing content is FROZEN — do NOT reproduce any of it:
---
{section_content}
---

These criteria have minor gaps (section already scores 75%+):
{criteria_lines}
{context_block}
Return ONLY <additions> and <modifications> blocks to close these gaps."""

    call_fn = llm_call_with_advisor if use_advisor else llm_call
    llm_output = call_fn(
        client, tracker, "improver",
        model="claude-sonnet-4-6",
        max_tokens=1500,
        temperature=0.2,
        system=POLISH_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    # Parse additions
    additions = []
    for match in re.finditer(
        r'<addition[^>]*>(.*?)</addition>', llm_output, re.DOTALL
    ):
        content = match.group(1).strip()
        if content:
            additions.append(content)

    # Parse modifications
    modifications = []
    for match in re.finditer(
        r'<modification[^>]*>(.*?)</modification>', llm_output, re.DOTALL
    ):
        content = match.group(1).strip()
        if content:
            modifications.append(content)

    result = section_content.rstrip()

    if additions:
        result += "\n\n"
        result += "\n\n".join(additions)

    if modifications:
        result += "\n\n### Minor Adjustments\n\n"
        result += "\n\n".join(modifications)

    return result