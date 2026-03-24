# agents/generator.py
import anthropic
try:
    import streamlit as st
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=api_key)

GENERATOR_SYSTEM_PROMPT = """You are an expert Digital Product Manager at ServiceNow \
who writes SAFe Feature specifications for cross-functional teams including engineering, \
devops, design, content, QA, SEO, and analytics.

You will receive structured Q&A answers organized by section. Use ALL of this \
information to generate a complete SAFe Feature specification.

Guidelines:
- Be specific and concrete — use the exact names, systems, teams, and numbers from the answers
- Where answers are marked [NEEDS INPUT: ...], write a brief placeholder noting what is needed
- Do not invent information not present in the answers

REQUIRED STRUCTURE — always include ALL of these ## headings:
## Feature Title
## Description
## Scope (In-Scope)
## Out of Scope
## Solution Approach
## SEO & Analytics
## Copywriting & Messaging
## Campaign Integration
## Design & Accessibility
## Engineering & Publishing
## Dependencies

REQUIRED CONTENT — always include regardless of notes quality:
- Under ## Dependencies: list all systems and teams mentioned anywhere in the answers
- Under ## Acceptance Criteria: generate at minimum 3 user stories with full Gherkin \
  acceptance criteria (Given/When/Then), prioritized P0-P4. This section is mandatory \
  and must never be empty or omitted. If notes are thin, generate user stories from \
  the feature description and solution approach.
- Under ## Acceptance Criteria: generate at minimum 3 user stories. Each story must:
  (1) follow INVEST principles — Independent, Negotiable, Valuable, Estimable, Small, Testable
  (2) include a traceability note linking it to a specific feature requirement
      e.g. "Supports: SEO Strategy requirement for meta tag optimization"
  (3) use Gherkin syntax for all acceptance criteria (Given/When/Then)
  (4) include P0-P4 priority assignment
  (5) include an effort estimate (S/M/L or story points)
  This section is mandatory and must never be empty.

FORMAT RULES:
- User story format: "As a [persona], I want to [action], so I can [benefit]."
- Acceptance criteria format: Given [context] / When [event] / Then [outcome]
- Priority format: P0 (highest) through P4 (lowest)
- Format output so it can be pasted directly into a SAFe tool"""


def generate_feature_spec(
    feature_type: str,
    preamble: str,
    section_answers: dict[str, str]
) -> str:
    """
    Generate a full SAFe Feature spec from PM-approved section answers.

    Args:
        feature_type:    CAPABILITY, EXPERIENCE, or WEBPAGE
        preamble:        The type-specific preamble from prompts/capabilities|experiences|webpages.py
        section_answers: Dict of {section_name: answer_text} — all sections combined

    Returns:
        Full SAFe Feature specification as a markdown string
    """
    # Build the context block from all section answers
    context_parts = []
    for section_name, answers in section_answers.items():
        context_parts.append(f"## {section_name}\n{answers}")

    full_context = "\n\n".join(context_parts)

    prompt = f"""Feature type: {feature_type}

The PM has provided the following answers through a structured interview.
Where answers are marked [NEEDS INPUT], write a brief placeholder noting what is needed.

{full_context}

Generate the complete SAFe Feature specification now."""

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=12000,
        temperature=0.3,
        system=GENERATOR_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text