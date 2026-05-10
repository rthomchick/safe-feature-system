# evaluation/token_tracker.py
from __future__ import annotations
# TokenTracker: accumulates LLM call usage within a single pipeline run.
# llm_call():   shared wrapper around client.messages.create() that records
#               usage before returning the text, so no agent needs to change
#               its return type.

import time
from dataclasses import dataclass, field
from pathlib import Path

from evaluation.eval_db import get_connection, is_postgres, DEFAULT_DB_PATH

# Pricing per million tokens (USD). Update when Anthropic changes prices.
_TOKEN_COSTS: dict[str, dict[str, float]] = {
    "claude-opus-4-7":            {"input": 15.00, "output": 75.00},
    "claude-opus-4-6":            {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-6":          {"input":  3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input":  3.00, "output": 15.00},
    "claude-haiku-4-5-20251001":  {"input":  0.80, "output":  4.00},
    "claude-haiku-4-5":           {"input":  0.80, "output":  4.00},
    "default":                    {"input":  3.00, "output": 15.00},
}


@dataclass
class TokenRecord:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    call_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))


class TokenTracker:
    """Accumulates per-call token usage for one pipeline run.

    Usage pattern:
        tracker = TokenTracker()
        text = llm_call(client, tracker, agent="reviewer", model=..., ...)
        # ... more calls ...
        tracker.flush_to_db(run_id)
    """

    def __init__(self) -> None:
        self._records: list[TokenRecord] = []

    def record(
        self,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        self._records.append(TokenRecord(agent, model, input_tokens, output_tokens))

    def total_tokens(self) -> dict[str, int]:
        return {
            "input": sum(r.input_tokens for r in self._records),
            "output": sum(r.output_tokens for r in self._records),
            "calls": len(self._records),
        }

    def total_cost_usd(self) -> float:
        cost = 0.0
        for r in self._records:
            pricing = _TOKEN_COSTS.get(r.model, _TOKEN_COSTS["default"])
            cost += (r.input_tokens  / 1_000_000) * pricing["input"]
            cost += (r.output_tokens / 1_000_000) * pricing["output"]
        return round(cost, 6)

    def by_agent(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for r in self._records:
            if r.agent not in result:
                result[r.agent] = {"input": 0, "output": 0, "calls": 0}
            result[r.agent]["input"]  += r.input_tokens
            result[r.agent]["output"] += r.output_tokens
            result[r.agent]["calls"]  += 1
        return result

    def summary(self) -> dict:
        totals = self.total_tokens()
        return {
            **totals,
            "cost_usd": self.total_cost_usd(),
            "by_agent": self.by_agent(),
        }

    def flush_to_db(self, run_id: str, db_path: Path | None = None) -> None:
        """Persist all accumulated records to the token_usage table."""
        ph = "%s" if is_postgres() else "?"
        with get_connection(db_path) as conn:
            conn.executemany(
                f"""INSERT INTO token_usage
                   (run_id, agent, model, input_tokens, output_tokens, call_at)
                   VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph})""",
                [
                    (run_id, r.agent, r.model, r.input_tokens, r.output_tokens, r.call_at)
                    for r in self._records
                ],
            )


def llm_call_with_advisor(
    client,
    tracker: TokenTracker | None,
    agent: str,
    advisor_model: str = "claude-opus-4-7",
    max_advisor_uses: int = 2,
    **kwargs,
) -> str:
    """llm_call() variant that enables the Opus advisor tool.

    Uses client.beta.messages.create() with the advisor-tool-2026-03-01 beta.
    The executor (Sonnet) drives the task; Opus advises when consulted.
    If the advisor is overloaded or hits max_uses, the executor continues
    without advice — no failure, just graceful degradation.

    Args:
        client:            anthropic.Anthropic instance
        tracker:           TokenTracker for the current run, or None
        agent:             pipeline stage name (e.g. "reviewer")
        advisor_model:     advisor model string (default "claude-opus-4-7")
        max_advisor_uses:  max advisor consultations per request (default 2)
        **kwargs:          passed to client.beta.messages.create()
                           (model, max_tokens, temperature, system, messages)

    Returns:
        Concatenated text from all text blocks in the response.
        Identical return type to llm_call().
    """
    advisor_tool = {
        "type": "advisor_20260301",
        "name": "advisor",
        "model": advisor_model,
        "max_uses": max_advisor_uses,
    }
    existing_tools = kwargs.pop("tools", None) or []
    kwargs["tools"] = existing_tools + [advisor_tool]

    response = client.beta.messages.create(
        betas=["advisor-tool-2026-03-01"],
        **kwargs,
    )

    text_parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)

    if tracker is not None:
        tracker.record(
            agent=agent,
            model=kwargs.get("model", "unknown"),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        for iteration in getattr(response.usage, "iterations", None) or []:
            if isinstance(iteration, dict):
                it_type = iteration.get("type")
                it_input = iteration.get("input_tokens", 0)
                it_output = iteration.get("output_tokens", 0)
                it_model = iteration.get("model", advisor_model)
            else:
                it_type = getattr(iteration, "type", None)
                it_input = getattr(iteration, "input_tokens", 0)
                it_output = getattr(iteration, "output_tokens", 0)
                it_model = getattr(iteration, "model", advisor_model)

            if it_type == "advisor_message":
                tracker.record(
                    agent=f"{agent}_advisor",
                    model=it_model,
                    input_tokens=it_input,
                    output_tokens=it_output,
                )

    return "\n".join(text_parts)


def llm_call(client, tracker: TokenTracker | None, agent: str, **kwargs) -> str:
    """Wrapper around client.messages.create() that records token usage.

    Drop-in replacement for the pattern:
        response = client.messages.create(...)
        return response.content[0].text

    Becomes:
        return llm_call(client, tracker, agent="reviewer", model=..., ...)

    Args:
        client:   anthropic.Anthropic instance
        tracker:  TokenTracker for the current run, or None to skip recording.
                  When None, behaves exactly like a direct client.messages.create() call.
        agent:    pipeline stage name (e.g. "router", "reviewer")
        **kwargs: passed directly to client.messages.create()

    Returns:
        response.content[0].text (identical to existing agent return values)
    """
    response = client.messages.create(**kwargs)
    if tracker is not None:
        tracker.record(
            agent=agent,
            model=kwargs.get("model", "unknown"),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
    return response.content[0].text
