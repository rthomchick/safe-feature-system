# agents/router.py
import os

import anthropic
import streamlit as st


def _get_api_key(key_name: str) -> str:
    """Retrieve API key from Streamlit secrets or environment; raise on missing."""
    try:
        return st.secrets[key_name]
    except Exception:
        pass
    value = os.environ.get(key_name)
    if not value:
        raise RuntimeError(
            f"Missing required API key: {key_name}. "
            f"Set it in .streamlit/secrets.toml or as an environment variable."
        )
    return value


api_key = _get_api_key("ANTHROPIC_API_KEY")
client = anthropic.Anthropic(api_key=api_key)

from evaluation.token_tracker import llm_call

ROUTER_SYSTEM_PROMPT = """You are a SAFe Feature type classifier for a digital product team at ServiceNow.

Given a description of work, classify it into exactly one of these three types:

CAPABILITY
- Backend functionality, platform infrastructure, APIs, integrations, or reusable engines
- The primary work is how a system works under the hood
- Examples: progressive profiling engine, Adobe Target integration, CDP event pipeline,
  buying group classification API, personalization token library
- Ask yourself: Is the core deliverable a system, tool, or engine — not a page or UI component?

EXPERIENCE
- UI components or interactive frontend features users directly see and interact with
- The primary work is how a component looks, behaves, and responds across states
- Examples: filter component, tabbed content module, sticky nav, product configurator,
  form with progressive disclosure logic
- Ask yourself: Is the core deliverable a component's visual behavior and interaction states?

WEBPAGE
- New web pages or updates to existing pages where the primary work is content,
  messaging, SEO, copywriting, or the publishing workflow
- Examples: new ITSM product page, marquee copy update, Knowledge 2025 campaign page,
  homepage hero refresh, new financial services solutions page
- Ask yourself: Is the core deliverable published content on a page?

TIEBREAKER RULES — when the work spans multiple types:
- Marquee update → WEBPAGE (work is messaging + publishing, not component behavior)
- Progressive profiling form → CAPABILITY if the engine/data logic is the core work;
  EXPERIENCE if the form UI component behavior is the core work
- Adobe Target + landing page → CAPABILITY for the integration; WEBPAGE for the page content
- New page with custom interactive element → WEBPAGE for the page; EXPERIENCE for the component
- When genuinely ambiguous, choose CAPABILITY over EXPERIENCE, and WEBPAGE over both
  if publishing/content is mentioned anywhere in the description

Respond with ONLY one word: CAPABILITY, EXPERIENCE, or WEBPAGE.
No explanation. No punctuation. No other text."""


ROUTER_SYSTEM_PROMPT_V2 = """You are a SAFe Feature type classifier for a digital product team at ServiceNow.

Given a description of work, classify it into exactly one of these three types:

CAPABILITY
- Backend functionality, platform infrastructure, APIs, integrations, or reusable engines
- The deliverable is a system, service, or data processing component with no user-visible UI
- Signal words: engine, pipeline, API, classification, scoring, data model, event schema,
  integration layer, identity resolution backend, buying group logic, token library
- Ask yourself: Is the core deliverable something that runs behind the scenes — defined by
  its data processing and system behavior, with no component states or design system spec?

EXPERIENCE
- UI components or interactive frontend features users directly see and interact with
- The deliverable is a component with named visual states, interaction behavior, and design
  system implementation — it has a design spec, not just backend logic
- Signal words: component, form component, design system, Arc Design System, component states,
  default state, loading state, error state, known-user variant, responsive behavior,
  keyboard navigation, ARIA, progressive disclosure UI, interactive behavior
- Ask yourself: Is the core deliverable a UI component with distinct visual states and
  interaction behavior? A form component that calls backend APIs is EXPERIENCE if the spec
  is primarily about what users see and interact with — not the backend logic underneath.

WEBPAGE
- New web pages or updates to existing pages where the primary work is content,
  messaging, SEO, copywriting, or the publishing workflow
- Signal words: page, landing page, solutions page, hero, SEO, meta title, CMS publishing,
  content strategy, copywriting, campaign page, hreflang
- Ask yourself: Is the core deliverable published content on a specific page (not a reusable
  component that can be placed on many pages)?

TIEBREAKER RULES — when the work spans multiple types:
- "Progressive profiling form component" with Arc Design System → EXPERIENCE
  (component states and UI behavior are the core work, not the backend engine)
- "Progressive profiling engine / classification API" → CAPABILITY
  (backend data logic is the core work; no UI component states)
- Adobe Target integration (backend) → CAPABILITY
  A form that uses Adobe Target to select a variant → EXPERIENCE
- New page with a custom interactive component → WEBPAGE for the page; EXPERIENCE for the component
- Marquee copy update / content refresh → WEBPAGE
- If the description explicitly names Arc Design System, component states, or design system
  patterns as core deliverables → EXPERIENCE (not CAPABILITY)
- If the description names SEO, meta tags, or content publishing as core work → WEBPAGE

Respond with ONLY one word: CAPABILITY, EXPERIENCE, or WEBPAGE.
No explanation. No punctuation. No other text."""


def classify_feature(description: str, tracker=None, system_prompt: str | None = None) -> str:
    """Classify a feature description into CAPABILITY, EXPERIENCE, or WEBPAGE.

    Args:
        description:   The feature description to classify.
        tracker:       Optional TokenTracker for recording LLM usage.
        system_prompt: Override the router system prompt (e.g. for A/B testing).
                       Defaults to ROUTER_SYSTEM_PROMPT if not supplied.
    """
    prompt = system_prompt if system_prompt is not None else ROUTER_SYSTEM_PROMPT
    result = llm_call(
        client, tracker, "router",
        model="claude-haiku-4-5-20251001",
        max_tokens=10,
        temperature=0.0,
        system=prompt,
        messages=[{"role": "user", "content": description}]
    ).strip().upper()

    # Parse defensively — extract the type even if Claude adds extra text
    for feature_type in ["CAPABILITY", "EXPERIENCE", "WEBPAGE"]:
        if feature_type in result:
            return feature_type

    return "CAPABILITY"  # Fallback default