# agents/draft_answerer.py
import anthropic
try:
    import streamlit as st
    api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=api_key)

DRAFT_SYSTEM_PROMPT = """You are a senior Digital Product Manager at ServiceNow helping \
draft answers for a SAFe Feature specification.

You will receive:
1. A feature type (Capability, Experience, or Webpage)
2. A section name and its questions
3. Context notes provided by the PM (meeting notes, strategy docs, requirements, \
   Slack messages — anything they have)

Your job:
- Read the notes carefully and extract relevant information for each question
- Draft a clear, specific answer to each question based on what the notes contain
- Write for a cross-functional audience: engineering, design, QA, SEO, analytics
- Be concrete — use actual names, systems, teams, and numbers from the notes when present
- Keep each answer focused: 2-4 sentences is typical, more only when the notes are rich

When the notes don't address a question:
- Write exactly: [NEEDS INPUT: <one sentence describing what information is needed>]
- Do not guess or invent information
- Do not write generic placeholder text like "TBD" or "To be determined"

Format your response as a clean list, one answer per question:

Q1: [full question text]
A1: [your drafted answer or NEEDS INPUT flag]

Q2: [full question text]
A2: [your drafted answer or NEEDS INPUT flag]

Continue for all questions in the section. Do not add preamble, summary, or closing remarks."""


def draft_section_answers(
    notes: str,
    feature_type: str,
    section_name: str,
    questions: list[str]
) -> str:
    """
    Draft answers for one section of questions based on PM's notes.

    Args:
        notes:        Raw notes/context pasted by the PM
        feature_type: CAPABILITY, EXPERIENCE, or WEBPAGE
        section_name: The section being answered (e.g. "Strategy & Purpose")
        questions:    List of question strings for this section

    Returns:
        Formatted string with Q/A pairs, ready to display in Streamlit
    """
    numbered_questions = "\n".join(
        f"Q{i+1}: {q}" for i, q in enumerate(questions)
    )

    prompt = f"""Feature type: {feature_type}
Section: {section_name}

PM's notes:
---
{notes}
---

Please draft answers to these questions:

{numbered_questions}"""

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2000,
        temperature=0.3,
        system=DRAFT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text