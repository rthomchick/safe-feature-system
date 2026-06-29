# ADR-001: Parse → Edit → Reassemble for Agent Output Modification

**Status:** Accepted
**Date:** 2026-03
**Repo:** safe-feature-system
**Decider:** Richard Thomchick

## Context

The SAFe Feature Spec Generator produces a structured multi-section document
across six agents. Early versions of the Improver agent modified spec sections
by treating the full spec as a string and performing positional surgery —
locating a section by searching for its header, extracting a substring, replacing
it, and splicing the result back into the full document.

This approach caused silent corruption: when section headers appeared more than
once (e.g. in examples within a section), the wrong substring was replaced.
When the Improver changed a section's length, downstream character offsets
shifted, causing subsequent edits to splice into the wrong location. Corruption
was not always visible immediately — it propagated into the next agent's input
and surfaced as malformed output several steps later, making root cause
diagnosis difficult.

## Decision

Replace all string-surgery modification with a Parse → Edit → Reassemble
pattern:

1. **Parse:** split the full spec into a dict keyed by section name at the
   start of any operation that modifies content
2. **Edit:** modify only the target section's value in the dict
3. **Reassemble:** join all sections in canonical order to produce the output

## Rationale

- Eliminates offset sensitivity — section boundaries are structural, not
  positional
- Makes the target of every edit explicit and auditable — the section key
  is named, not inferred from character position
- Idempotent reassembly guarantees output structure regardless of how many
  edit passes run
- Easier to test — each section can be verified independently before
  reassembly

## Consequences

- All agents that modify spec content must parse first; cannot operate on
  raw string output directly
- Section header format must be consistent across all agents to enable
  reliable parsing — enforced via a shared parser function
- Adds one parse and one reassemble step per improvement cycle; negligible
  performance cost at current scale
