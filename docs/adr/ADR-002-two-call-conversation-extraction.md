# ADR-002: Two-Call Architecture for Conversational Extraction

**Status:** Accepted
**Date:** 2026-05
**Repo:** safe-feature-system
**Decider:** Richard Thomchick

## Context

The SAFe Intake Copilot needed to do two things in each turn: produce a
natural language conversational response for the stakeholder, and extract
structured data from what the stakeholder said for downstream pipeline use.

The first implementation attempted both in a single API call by asking Claude
to produce a conversational reply and simultaneously invoke a structured
extraction tool. This produced a persistent failure mode: the model would
either return only the tool call (skipping the conversational text entirely)
or return only the text (skipping the tool call). Reliable co-production of
both in one call was not achievable at any prompt configuration tested.

## Decision

Split into two separate API calls with distinct responsibilities:

1. **Call 1 — Conversation:** no tools available; model is forced to produce
   natural language only; handles the stakeholder-facing dialogue turn
2. **Call 2 — Extraction:** forced tool call with `tool_choice="any"`;
   operates on the conversation history to extract structured
   IntakeRecord fields; never shown to the stakeholder

## Rationale

- Eliminates the stub response failure mode by making tool use and text
  generation mutually exclusive per call
- Each call can be independently prompted, tested, and monitored — the
  conversational prompt optimizes for tone and adaptive questioning; the
  extraction prompt optimizes for field accuracy and gap detection
- Extraction operates on the full conversation history, not just the most
  recent turn — produces more accurate field population than turn-by-turn
  extraction would
- Cost overhead is acceptable: Call 2 (extraction) uses a smaller context
  and shorter output than Call 1; total cost per turn remains within budget

## Consequences

- Every copilot turn requires two API calls; latency is additive
- Conversation history must be passed to both calls — state management is
  the caller's responsibility
- Extraction accuracy depends on conversation quality from Call 1; a poor
  conversational turn produces less extractable signal
- The pattern generalizes: any agent that needs both user-facing output and
  structured side-effects should use this two-call split rather than
  attempting to combine them
