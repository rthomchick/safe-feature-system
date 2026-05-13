# intake_copilot/agent.py
from __future__ import annotations

import json
from typing import Any, Optional

import anthropic

try:
    import streamlit as st
    _api_key = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    import os
    _api_key = os.environ.get("ANTHROPIC_API_KEY")

from evaluation.token_tracker import TokenTracker
from intake_copilot.models import (
    ConversationManager,
    ConversationState,
    FieldStatus,
    IntakeRecord,
    ReadinessScorer,
)

_MODEL = "claude-sonnet-4-5-20250929"
_ADVISOR_MODEL = "claude-opus-4-6"
_MAX_TOKENS = 1024
_ADVISOR_BETA = "advisor-tool-2026-03-01"

# Set to True via IntakeCopilot(debug=True) to print raw API I/O each turn.
_DEBUG = False


def _debug_print_messages(system: str, messages: list) -> None:
    print("\n" + "=" * 70)
    print("DEBUG — MESSAGES SENT TO API")
    print("=" * 70)
    print(f"[system] {system[:200]}{'…' if len(system) > 200 else ''}")
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            print(f"[{i}] {role}: {content}")
        else:
            print(f"[{i}] {role}: {content!r}")
    print("=" * 70)


def _debug_print_response(response_content: list) -> None:
    print("\n" + "─" * 70)
    print("DEBUG — RAW API RESPONSE CONTENT BLOCKS")
    print("─" * 70)
    for i, block in enumerate(response_content):
        block_type = getattr(block, "type", "?")
        if block_type == "text":
            print(f"[block {i}] type=text\n{block.text}")
        elif block_type == "tool_use":
            print(f"[block {i}] type=tool_use  name={block.name}")
            import json as _json
            print(_json.dumps(block.input, indent=2))
        else:
            print(f"[block {i}] type={block_type}  {block!r}")
    print("─" * 70 + "\n")

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

COPILOT_SYSTEM_PROMPT = """\
You are a friendly, efficient intake coordinator for a website product team. \
Your job is to understand what the stakeholder needs and capture it clearly \
for the product manager.

TONE
Warm but efficient — like a good colleague who listens well and asks smart questions. \
Never robotic, never overly casual. \
Reflect back what you hear before asking follow-up questions.

LANGUAGE RULES (strict)
Never use: "SAFe", "feature type", "CAPABILITY", "EXPERIENCE", "WEBPAGE", \
"acceptance criteria", "user stories", or any product/engineering jargon. \
Frame all questions in the stakeholder's language. \
Examples of translations:
  - "What are your success metrics?" → "How would you know this was working?"
  - "Who is the target audience?" → "Who would be using this, or landing on this page?"
  - "What are the dependencies?" → "Is there anything else that needs to be in place first?"

WHEN THE STAKEHOLDER SAYS "I DON'T KNOW"
Respond warmly: "That's totally fine — the product team can figure that part out. \
Let me ask about something else."

QUESTION GROUPING
When asking multiple questions, group at most 2 related ones together. \
Never list 3 or more questions in one turn.

TRANSITIONS
Before asking context or detail questions, use a transition: \
"You've painted a clear picture of the core need. \
A couple more details would help the product team..."

SUMMARY FORMAT
When it is time to summarize, present a clean, structured summary in plain language. \
Clearly mark what is known vs. what the product team will need to figure out. \
End with: "Does this capture what you're looking for? \
Feel free to correct anything."

LANGUAGE VARIETY
Vary your acknowledgment language. \
Don't repeat phrases like "really helpful," "that's helpful," or "thanks for sharing that" \
across turns. \
Use a mix of acknowledgments: "Got it," "That makes sense," "Good to know," "Understood," \
"That clarifies things," etc. \
Each turn should feel fresh, not formulaic.

ADVISOR
You have access to an advisor for difficult judgment calls. \
Consult it when you're unsure how to classify the request \
(is this a new page, a change to an existing experience, or a platform capability?) \
or when the stakeholder's answer is ambiguous and you're not sure how to proceed. \
Don't consult it for routine questions.

HIDDEN CONTEXT
You will receive a JSON block labeled INTAKE_STATE at the start of each turn. \
This contains the current state of the intake record — which fields are populated, \
which are gaps, and what action the conversation manager recommends next. \
Use this to guide your questions. \
The stakeholder cannot see this block. \
Never reference field names, weights, scores, or the intake data model in your responses.

GREETING TEMPLATE (use verbatim for the first message)
Hi! I help turn website requests into clear specs for the product team. \
Just describe what you need — whether it's a new page, a change to something existing, \
or a new capability — in whatever level of detail you have. \
I'll ask a few follow-up questions to make sure the team has what they need. \
Most conversations take about 5 minutes.\
"""

# ---------------------------------------------------------------------------
# Extraction system prompt (used only for Call 2 — the update_intake call)
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a precise data-extraction assistant. Your only job is to call the \
update_intake tool to record what the stakeholder explicitly said in their \
most recent message.

FIELD DEFINITIONS — read carefully before populating

- problem_statement: What is broken, missing, or painful TODAY? \
Describe the current state that needs to change. \
Example: "Customers cannot see their pricing without contacting their rep."

- business_objective: Why does the BUSINESS care about fixing this? \
What strategic or financial outcome does solving this problem enable? \
Example: "Retain a $2M ARR account at risk of churn; reduce support cost \
from pricing inquiries; address demand from multiple enterprise accounts."

- success_metrics: How would you MEASURE whether the solution worked? \
What specific numbers or signals would change? \
Example: "Fewer pricing-related support tickets; Meridian stops escalating \
through their CSM."

Disambiguation test — when a statement could fit multiple fields, ask:
  "What's wrong today?" → problem_statement
  "Why should we fix it?" → business_objective
  "How would we know it's fixed?" → success_metrics
If a statement genuinely spans two fields (e.g., "fewer support tickets" is \
both an objective and a metric), populate BOTH fields with the relevant framing.

STRICT RULES

Only mark a field as 'populated' if the stakeholder explicitly provided that \
information in their most recent message. Do not infer, assume, or extrapolate.

If the stakeholder mentioned something tangentially related to a field but did \
not directly address it, leave that field out of your tool call entirely — do \
not populate it with an inference.

Only update fields where the stakeholder's MOST RECENT message provided new \
information. Do not re-populate fields that were already captured in previous \
turns (you can see the current intake state in the user message).

Only mark a field as 'unknown' if the stakeholder explicitly said they don't \
know or can't answer (e.g., "I don't know", "not sure", "TBD"). Do not mark \
fields unknown just because they weren't mentioned.

When in doubt, leave the field out. Accurate gaps are more useful than false \
completeness — the PM will fill remaining gaps.

EXAMPLES OF WHAT NOT TO DO

Stakeholder says: "it's for a Q3 renewal campaign."
  ✓ Populate: timeline_constraints = "Q3 renewal campaign"
  ✗ Do NOT populate: success_metrics, dependencies, scope_exclusions, \
target_audience (none of these were addressed)

Stakeholder says: "we need a page where customers can see their pricing."
  ✓ Populate: problem_statement, feature_name (inferred from description)
  ✗ Do NOT populate: business_objective, success_metrics, solution_approach \
(not stated — these are gaps to explore)
"""

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_FIELD_NAMES = [
    "feature_name",
    "feature_type",
    "problem_statement",
    "business_objective",
    "target_audience",
    "success_metrics",
    "dependencies",
    "timeline_constraints",
    "solution_approach",
    "scope_inclusions",
    "scope_exclusions",
    "additional_context",
]

INTAKE_UPDATE_TOOL: dict[str, Any] = {
    "name": "update_intake",
    "description": (
        "Update the intake record with information learned from the stakeholder's response."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_name": {
                            "type": "string",
                            "enum": _FIELD_NAMES,
                        },
                        "value": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["populated", "unknown"],
                        },
                    },
                    "required": ["field_name", "status"],
                },
            },
            "feature_type_guess": {
                "type": "string",
                "enum": ["CAPABILITY", "EXPERIENCE", "WEBPAGE", "uncertain"],
            },
            "feature_type_confidence": {"type": "number"},
            "conversation_note": {
                "type": "string",
                "description": (
                    "Brief note about the stakeholder's knowledge level and engagement"
                ),
            },
        },
    },
}


ADVISOR_TOOL: dict[str, Any] = {
    "type": "advisor_20260301",
    "name": "advisor",
    "model": _ADVISOR_MODEL,
    "max_uses": 2,
}

# ---------------------------------------------------------------------------
# Borderline recommendation thresholds
# ---------------------------------------------------------------------------

_BORDERLINE_SCORE_LOW = 10
_BORDERLINE_SCORE_HIGH = 15
_BORDERLINE_CONFIDENCE = 0.8
_BORDERLINE_CORE_IDK = 3

# ---------------------------------------------------------------------------
# IntakeCopilot
# ---------------------------------------------------------------------------

class IntakeCopilot:

    def __init__(self, tracker: Optional[TokenTracker] = None, debug: bool = False) -> None:
        self._client = anthropic.Anthropic(api_key=_api_key)
        self._tracker = tracker
        self._debug = debug
        self._record = IntakeRecord()
        self._manager = ConversationManager()
        self._scorer = ReadinessScorer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def greeting(self) -> str:
        """Return the opening message and advance conversation state."""
        self._manager.state = ConversationState.INITIAL_PROCESSING
        # Extract just the greeting template from the system prompt
        marker = "GREETING TEMPLATE (use verbatim for the first message)\n"
        idx = COPILOT_SYSTEM_PROMPT.find(marker)
        if idx != -1:
            greeting_text = COPILOT_SYSTEM_PROMPT[idx + len(marker):].strip()
        else:
            greeting_text = (
                "Hi! I help turn website requests into clear specs for the product team. "
                "Just describe what you need — whether it's a new page, a change to "
                "something existing, or a new capability — in whatever level of detail "
                "you have. I'll ask a few follow-up questions to make sure the team has "
                "what they need. Most conversations take about 5 minutes."
            )
        self._record.conversation_history.append(
            {"role": "assistant", "content": greeting_text}
        )
        return greeting_text

    _CONFIRMATION_PHRASES = frozenset([
        "yes", "yeah", "yep", "yup", "correct", "confirmed", "confirm",
        "looks good", "looks right", "that's right", "that's correct",
        "that's it", "that works", "perfect", "exactly", "approved", "great",
        "sounds good", "sounds right", "all good", "good to go",
        "ship it", "send it", "let's go", "let's do it", "all set",
        "we're good", "do it", "go ahead", "go for it", "nailed it",
        "absolutely", "definitely", "for sure",
    ])

    _CLOSING_MESSAGE = (
        "Great, I'll get this over to the product team. They may follow up if they need "
        "any additional details, but you've given them a solid foundation to work with. "
        "Thanks for your time!"
    )

    def process_turn(self, user_message: str) -> str:
        """Process one stakeholder turn and return the copilot's reply."""
        # Handle post-summary confirmation without an API call
        if self._manager.state == ConversationState.SUMMARIZING and self._is_confirmation(user_message):
            self._manager.state = ConversationState.CONFIRMED
            self._record.conversation_history.append(
                {"role": "user", "content": user_message}
            )
            self._record.conversation_history.append(
                {"role": "assistant", "content": self._CLOSING_MESSAGE}
            )
            return self._CLOSING_MESSAGE

        self._manager.state = ConversationState.ASKING_QUESTIONS

        # Append user message to history (will be sent to API)
        self._record.conversation_history.append(
            {"role": "user", "content": user_message}
        )
        # Store raw input on first real turn
        if not self._record.stakeholder_input_raw:
            self._record.stakeholder_input_raw = user_message

        # Build messages for this API call
        messages = self._build_messages(user_message)

        # ── Call 1: conversation (advisor tool available, text response expected) ──
        if self._debug:
            print(f"\nDEBUG — CALL 1 (conversation, betas=[{_ADVISOR_BETA}], advisor tool)")
            _debug_print_messages(COPILOT_SYSTEM_PROMPT, messages)

        conv_response = None
        _advisor_used_beta = False
        try:
            conv_response = self._client.beta.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=COPILOT_SYSTEM_PROMPT,
                tools=[ADVISOR_TOOL],
                betas=[_ADVISOR_BETA],
                messages=messages,
            )
            _advisor_used_beta = True
        except anthropic.APIError as exc:
            if self._debug:
                print(f"DEBUG — advisor beta call failed ({exc}); falling back to standard call")
            self._record.advisor_consultations.append({
                "type": "advisor_fallback",
                "reason": str(exc),
                "turn": len(self._record.conversation_history),
            })

        if conv_response is None:
            try:
                conv_response = self._client.messages.create(
                    model=_MODEL,
                    max_tokens=_MAX_TOKENS,
                    system=COPILOT_SYSTEM_PROMPT,
                    messages=messages,
                )
            except anthropic.APIError as exc:
                self._record.conversation_history.pop()
                return (
                    "I'm sorry, I ran into a technical issue. "
                    "Could you repeat your last message? "
                    f"(Error: {exc})"
                )

        if self._tracker is not None:
            self._tracker.record(
                agent="intake_copilot",
                model=_MODEL,
                input_tokens=conv_response.usage.input_tokens,
                output_tokens=conv_response.usage.output_tokens,
            )

        if self._debug:
            _debug_print_response(conv_response.content)

        # Log any advisor consultation and collect redacted blocks to round-trip
        advisor_blocks = self._extract_and_log_advisor_blocks(conv_response.content)
        _ = advisor_blocks  # retained for future multi-turn round-tripping if needed

        reply_text = self._parse_text_response(conv_response)

        # Retry once if the conversation call returned no text
        if not reply_text:
            if self._debug:
                print("DEBUG — Call 1 returned no text; retrying conversation call")
            try:
                if _advisor_used_beta:
                    retry_response = self._client.beta.messages.create(
                        model=_MODEL,
                        max_tokens=_MAX_TOKENS,
                        system=COPILOT_SYSTEM_PROMPT,
                        tools=[ADVISOR_TOOL],
                        betas=[_ADVISOR_BETA],
                        messages=messages,
                    )
                else:
                    retry_response = self._client.messages.create(
                        model=_MODEL,
                        max_tokens=_MAX_TOKENS,
                        system=COPILOT_SYSTEM_PROMPT,
                        messages=messages,
                    )
                if self._tracker is not None:
                    self._tracker.record(
                        agent="intake_copilot",
                        model=_MODEL,
                        input_tokens=retry_response.usage.input_tokens,
                        output_tokens=retry_response.usage.output_tokens,
                    )
                reply_text = self._parse_text_response(retry_response)
            except anthropic.APIError:
                pass

        # ── Call 2: extraction (tool_choice=any — guaranteed tool call) ──
        intake_state = self._build_intake_state_block()
        extraction_messages = [
            {
                "role": "user",
                "content": (
                    "Here is the current intake state (fields already captured):\n"
                    f"{json.dumps(intake_state, indent=2)}\n\n"
                    "The stakeholder's most recent message was:\n"
                    f'"""\n{user_message}\n"""\n\n'
                    "Call update_intake to record only what their most recent message "
                    "explicitly provided. Follow the strict rules in your instructions."
                ),
            },
        ]

        if self._debug:
            print(f"\nDEBUG — CALL 2 (extraction, system=EXTRACTION_SYSTEM_PROMPT)")
            _debug_print_messages(EXTRACTION_SYSTEM_PROMPT, extraction_messages)

        tool_input: Optional[dict[str, Any]] = None
        try:
            ext_response = self._client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=EXTRACTION_SYSTEM_PROMPT,
                tools=[INTAKE_UPDATE_TOOL],
                tool_choice={"type": "any"},
                messages=extraction_messages,
            )
            if self._tracker is not None:
                self._tracker.record(
                    agent="intake_copilot",
                    model=_MODEL,
                    input_tokens=ext_response.usage.input_tokens,
                    output_tokens=ext_response.usage.output_tokens,
                )
            if self._debug:
                _debug_print_response(ext_response.content)
            tool_input = self._parse_tool_response(ext_response)
        except anthropic.APIError:
            pass  # extraction failure is non-fatal; conversation reply is already good

        if tool_input:
            self._apply_tool_input(tool_input)

        # Update IDK streak at the turn level, not per-field
        if self._is_idk(user_message):
            self._manager.record_turn_idk()
        else:
            self._manager.record_turn_answered()

        self._record.conversation_history.append(
            {"role": "assistant", "content": reply_text}
        )

        # Check whether we should advance to summarizing — via ConversationManager
        # logic OR by detecting a summary in the copilot's own response
        next_action = self._manager.next_action(self._record)
        if next_action == "summarize" or self._detect_summary_in_response(reply_text):
            self._manager.state = ConversationState.SUMMARIZING

        return reply_text

    def get_summary(self) -> dict[str, Any]:
        """Plain-language summary for the stakeholder confirmation step."""
        record = self._record

        def _val(field_name: str) -> str:
            f = getattr(record, field_name)
            if f.is_populated():
                return f.value or ""
            if f.status == FieldStatus.UNKNOWN:
                return "Stakeholder is unsure — product team to determine"
            return "Not yet captured"

        return {
            "feature_name": _val("feature_name"),
            "what_is_needed": _val("problem_statement"),
            "why_it_matters": _val("business_objective"),
            "who_it_is_for": _val("target_audience"),
            "how_we_will_know_it_works": _val("success_metrics"),
            "what_is_in_scope": _val("scope_inclusions"),
            "what_is_out_of_scope": _val("scope_exclusions"),
            "approach": _val("solution_approach"),
            "dependencies": _val("dependencies"),
            "timeline": _val("timeline_constraints"),
            "additional_context": _val("additional_context"),
            "knowledge_boundary": record.knowledge_boundary(),
        }

    def get_recommendation(self) -> dict[str, Any]:
        """PM-facing recommendation from the ReadinessScorer."""
        return self._scorer.recommendation(self._record)

    def get_advisor_recommendation(self) -> dict[str, Any]:
        """
        PM-facing recommendation enriched by Opus advisor when the case is borderline.
        Returns the base recommendation plus an 'advisor_input' key if consulted.
        """
        base = self._scorer.recommendation(self._record)
        if not self._is_borderline(base):
            return base

        record_summary = json.dumps(self._build_intake_state_block(), indent=2)
        prompt = (
            f"Review this intake record and give a concise recommendation "
            f"(accept / accept_with_caveats / needs_more_input) with rationale.\n\n"
            f"Base scorer says: {base['action']}\n"
            f"Rationale: {base['rationale']}\n\n"
            f"Full intake state:\n{record_summary}"
        )

        advisor_input: Optional[str] = None
        try:
            adv_response = self._client.beta.messages.create(
                model=_MODEL,
                max_tokens=512,
                system=(
                    "You are a senior product manager reviewing a website feature intake. "
                    "Be concise and direct."
                ),
                tools=[ADVISOR_TOOL],
                betas=[_ADVISOR_BETA],
                messages=[{"role": "user", "content": prompt}],
            )
            # Extract advisor result text if consulted
            for block in adv_response.content:
                block_type = getattr(block, "type", None)
                if block_type == "advisor_tool_result":
                    content = getattr(block, "content", None)
                    if content and hasattr(content, "text"):
                        advisor_input = content.text
                        break
                elif block_type == "text":
                    advisor_input = block.text  # fallback: Sonnet's own synthesis
        except anthropic.APIError:
            pass  # non-fatal; return base recommendation

        result = dict(base)
        if advisor_input:
            result["advisor_input"] = advisor_input
            self._record.advisor_consultations.append({
                "type": "pm_recommendation",
                "note": advisor_input,
                "turn": len(self._record.conversation_history),
            })
        return result

    def get_intake_record(self) -> IntakeRecord:
        """Full intake record for the PM review interface."""
        return self._record

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_and_log_advisor_blocks(self, content_blocks: list) -> list:
        """
        Scan response content for advisor_tool_use / advisor_tool_result blocks.
        Log each consultation to IntakeRecord and return redacted_result blocks
        for potential round-tripping.
        """
        redacted = []
        for block in content_blocks:
            block_type = getattr(block, "type", None)
            if block_type == "advisor_tool_result":
                inner = getattr(block, "content", None)
                inner_type = getattr(inner, "type", None)
                if inner_type == "advisor_result":
                    self._record.advisor_consultations.append({
                        "type": "advisor_result",
                        "note": getattr(inner, "text", ""),
                        "turn": len(self._record.conversation_history),
                    })
                elif inner_type == "advisor_redacted_result":
                    redacted.append(block)
                    self._record.advisor_consultations.append({
                        "type": "advisor_redacted_result",
                        "turn": len(self._record.conversation_history),
                    })
        return redacted

    def _is_borderline(self, recommendation: dict[str, Any]) -> bool:
        """Return True when the recommendation warrants advisor enrichment."""
        record = self._record
        score = record.readiness_score()
        core_idks = sum(
            1 for f in record._all_fields()
            if f.tier == "core" and f.status == FieldStatus.UNKNOWN
        )
        return (
            _BORDERLINE_SCORE_LOW <= score <= _BORDERLINE_SCORE_HIGH
            or record.feature_type_confidence < _BORDERLINE_CONFIDENCE
            or core_idks >= _BORDERLINE_CORE_IDK
        )

    def _parse_text_response(self, response: Any) -> str:
        """Extract and return the concatenated text from a tools-free API response."""
        parts = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts).strip()

    def _parse_tool_response(self, response: Any) -> Optional[dict[str, Any]]:
        """Extract the update_intake tool input from an extraction API response."""
        for block in response.content:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "update_intake"
            ):
                return block.input
        return None

    _IDK_PHRASES = frozenset([
        "i don't know", "i dont know", "i do not know", "not sure", "unsure",
        "no idea", "idk", "don't know", "dont know", "unknown", "no clue",
        "can't say", "cant say", "not certain", "i'm not sure", "im not sure",
    ])

    def _is_idk(self, text: str) -> bool:
        """Return True when the stakeholder's message is essentially 'I don't know'."""
        normalized = text.lower().strip()
        if normalized in self._IDK_PHRASES:
            return True
        return any(phrase in normalized for phrase in self._IDK_PHRASES if len(phrase) > 4)

    def _is_confirmation(self, text: str) -> bool:
        """Return True when any confirmation phrase appears anywhere in the message."""
        normalized = text.lower().strip()
        return any(phrase in normalized for phrase in self._CONFIRMATION_PHRASES)

    _SUMMARY_SIGNALS = (
        "does this capture what you're looking for",
        "feel free to correct anything",
        "does this reflect what you had in mind",
        "does that look right",
    )

    def _detect_summary_in_response(self, text: str) -> bool:
        """Return True when the copilot's response looks like a structured summary."""
        lower = text.lower()
        return any(signal in lower for signal in self._SUMMARY_SIGNALS)

    def _build_messages(self, current_user_message: str) -> list[dict[str, Any]]:
        """
        Build the messages array:
          - All prior conversation turns (history minus the current user message
            we just appended)
          - An injected INTAKE_STATE context block as a user message
          - The actual current user message

        We inject INTAKE_STATE as a separate user turn directly before the current
        message so the model treats it as system-level context without exposing it
        to the stakeholder.
        """
        # History already includes the current user message at [-1]; exclude it
        prior_history = self._record.conversation_history[:-1]

        messages: list[dict[str, Any]] = list(prior_history)

        intake_state = self._build_intake_state_block()
        messages.append({
            "role": "user",
            "content": f"INTAKE_STATE\n{json.dumps(intake_state, indent=2)}",
        })
        messages.append({"role": "assistant", "content": "Understood."})
        messages.append({"role": "user", "content": current_user_message})

        return messages

    def _build_intake_state_block(self) -> dict[str, Any]:
        record = self._record
        gaps = record.gap_inventory()
        return {
            "readiness_score": record.readiness_score(),
            "feature_type_confidence": record.feature_type_confidence,
            "next_action": self._manager.next_action(record),
            "consecutive_idk_count": self._manager.consecutive_idk_count,
            "asked_fields": sorted(self._manager.asked_fields),
            "gaps": gaps,
            "knowledge_boundary": record.knowledge_boundary(),
            "populated_fields": {
                f.name: f.value
                for f in record._all_fields()
                if f.is_populated()
            },
        }

    def _apply_tool_input(self, tool_input: dict[str, Any]) -> None:
        """Apply an update_intake tool call to the IntakeRecord."""
        record = self._record

        for field_update in tool_input.get("fields", []):
            field_name = field_update.get("field_name")
            if not field_name or not hasattr(record, field_name):
                continue

            intake_field = getattr(record, field_name)
            raw_status = field_update.get("status", "populated")
            status = (
                FieldStatus.POPULATED if raw_status == "populated" else FieldStatus.UNKNOWN
            )
            value = field_update.get("value") if raw_status == "populated" else None

            intake_field.status = status
            intake_field.value = value

            self._manager.record_answer(field_name, status)

        if "feature_type_guess" in tool_input:
            guess = tool_input["feature_type_guess"]
            if guess != "uncertain":
                record.feature_type.value = guess
                record.feature_type.status = FieldStatus.POPULATED
            record.feature_type_confidence = float(
                tool_input.get("feature_type_confidence", 0.0)
            )

        if "conversation_note" in tool_input:
            record.advisor_consultations.append({
                "type": "conversation_note",
                "note": tool_input["conversation_note"],
                "turn": len(record.conversation_history),
            })
