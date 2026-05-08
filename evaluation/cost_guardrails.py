"""
evaluation/cost_guardrails.py

Spending limits and enforcement for the SAFe Feature Spec pipeline.

Integration pattern — two options, both backward compatible:

    Option A: standalone guard alongside an existing TokenTracker
        tracker = TokenTracker()
        guard   = CostGuard()
        # Before each LLM call:
        guard.check_before_call("reviewer")
        # After llm_call() records usage into tracker, sync the guard:
        guard.sync_from_tracker(tracker)

    Option B: use llm_call_guarded() which wraps both steps atomically
        tracker = TokenTracker()
        guard   = CostGuard()
        text = llm_call_guarded(client, tracker, guard, agent="reviewer", ...)

    When guard=None, llm_call_guarded() falls back to plain llm_call() — fully
    backward compatible; no call sites need to change unless they want limits.

Standalone smoke test:
    python -m evaluation.cost_guardrails
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any

from evaluation.eval_db import get_connection, DEFAULT_DB_PATH
from evaluation.token_tracker import TokenTracker, llm_call, _TOKEN_COSTS


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COST_LIMITS: dict[str, float | int] = {
    # Maximum USD cost for a single complete pipeline run
    "per_run_max": 0.50,
    # Maximum USD cost for a single improvement-pass sub-run
    "per_improvement_max": 0.25,
    # Maximum cumulative USD cost across all runs recorded today (UTC)
    "daily_max": 5.00,
    # Maximum number of improvement iterations before the loop is force-stopped
    "improvement_iterations_max": 3,
}

# Fraction of a limit at which WARN is issued (HALT is at 100%)
_WARN_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class CostLimitExceeded(RuntimeError):
    """Raised by CostGuard.check_before_call() when a HALT threshold is hit."""

    def __init__(self, message: str, action: str, warnings: list[str]) -> None:
        super().__init__(message)
        self.action   = action
        self.warnings = warnings


# ---------------------------------------------------------------------------
# check_cost_budget — stateless helper
# ---------------------------------------------------------------------------

def check_cost_budget(
    current_run_cost: float,
    daily_total: float,
) -> dict[str, Any]:
    """Evaluate current spending against configured limits.

    Args:
        current_run_cost: Accumulated USD cost for the current run so far.
        daily_total:      Total USD cost for all runs today (from the DB),
                          NOT including current_run_cost (which may not yet
                          be flushed).

    Returns:
        {
            "action":   "PROCEED" | "WARN" | "HALT",
            "warnings": [...],          # empty when action is PROCEED
            "current_run_cost": float,
            "daily_total":      float,
        }
    """
    warnings: list[str] = []
    action = "PROCEED"

    per_run_max: float = float(COST_LIMITS["per_run_max"])
    daily_max:   float = float(COST_LIMITS["daily_max"])

    # ── Per-run checks ────────────────────────────────────────────────────────
    if current_run_cost >= per_run_max:
        action = "HALT"
        warnings.append(
            f"Per-run cost ${current_run_cost:.4f} has reached the "
            f"${per_run_max:.2f} limit."
        )
    elif current_run_cost >= per_run_max * _WARN_THRESHOLD:
        if action == "PROCEED":
            action = "WARN"
        warnings.append(
            f"Per-run cost ${current_run_cost:.4f} is above "
            f"{int(_WARN_THRESHOLD * 100)}% of the ${per_run_max:.2f} limit."
        )

    # ── Daily checks ──────────────────────────────────────────────────────────
    combined_daily = daily_total + current_run_cost
    if combined_daily >= daily_max:
        action = "HALT"
        warnings.append(
            f"Daily spend ${combined_daily:.4f} has reached the "
            f"${daily_max:.2f} daily limit."
        )
    elif combined_daily >= daily_max * _WARN_THRESHOLD:
        if action == "PROCEED":
            action = "WARN"
        warnings.append(
            f"Daily spend ${combined_daily:.4f} is above "
            f"{int(_WARN_THRESHOLD * 100)}% of the ${daily_max:.2f} daily limit."
        )

    return {
        "action":            action,
        "warnings":          warnings,
        "current_run_cost":  round(current_run_cost, 6),
        "daily_total":       round(daily_total, 6),
    }


# ---------------------------------------------------------------------------
# get_daily_spend — DB query
# ---------------------------------------------------------------------------

def get_daily_spend(db_path: Path = DEFAULT_DB_PATH) -> float:
    """Sum estimated USD cost of all token_usage rows recorded today (UTC).

    Uses the same per-model pricing table as token_tracker.py.
    Returns 0.0 if the table is empty or the DB does not exist yet.
    """
    if not db_path.exists():
        return 0.0

    today = date.today().isoformat()  # 'YYYY-MM-DD'

    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT model,
                   SUM(input_tokens)  AS input_tokens,
                   SUM(output_tokens) AS output_tokens
            FROM   token_usage
            WHERE  DATE(call_at) = ?
            GROUP  BY model
            """,
            (today,),
        ).fetchall()

    total = 0.0
    for r in rows:
        pricing = _TOKEN_COSTS.get(r["model"], _TOKEN_COSTS["default"])
        total += (r["input_tokens"]  / 1_000_000) * pricing["input"]
        total += (r["output_tokens"] / 1_000_000) * pricing["output"]

    return round(total, 6)


# ---------------------------------------------------------------------------
# CostGuard — stateful per-run enforcer
# ---------------------------------------------------------------------------

class CostGuard:
    """Stateful cost enforcer for one pipeline run.

    Tracks accumulated cost within the run and checks limits before each LLM
    call.  Designed to be paired with a TokenTracker: after each llm_call(),
    call guard.sync_from_tracker(tracker) to keep the guard's running total
    current.  Or use llm_call_guarded() which does both atomically.

    Args:
        db_path:        Path to the eval SQLite DB (for get_daily_spend).
        limit_key:      Which per-call limit to enforce:
                          "per_run_max"         (default — full pipeline run)
                          "per_improvement_max" (improvement sub-runs)
        daily_spend:    Pre-fetched daily spend. If None, fetched once lazily
                        on the first check. Pass 0.0 to skip the DB query
                        (e.g. in tests).
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        limit_key: str = "per_run_max",
        daily_spend: float | None = None,
    ) -> None:
        self.db_path      = db_path
        self.limit_key    = limit_key
        self._run_cost    = 0.0
        self._daily_spend = daily_spend   # None means "fetch lazily"
        self._last_result: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def run_cost(self) -> float:
        return round(self._run_cost, 6)

    def sync_from_tracker(self, tracker: TokenTracker) -> None:
        """Update the guard's running total from a TokenTracker.

        Call this after each llm_call() so the guard sees the latest spend
        before the next check.
        """
        self._run_cost = tracker.total_cost_usd()

    def add_cost(self, cost_usd: float) -> None:
        """Increment accumulated run cost directly (for testing or custom pipelines)."""
        self._run_cost += cost_usd

    def check_before_call(self, agent_name: str) -> dict[str, Any]:
        """Check spending limits before an LLM call.

        Args:
            agent_name: Name of the pipeline stage about to call the LLM
                        (used in warning messages only).

        Returns:
            Result dict from check_cost_budget() with action PROCEED or WARN.

        Raises:
            CostLimitExceeded: When action is HALT — the LLM call must not proceed.
        """
        # Apply the correct per-call cap
        original_limit = COST_LIMITS.get("per_run_max")
        cap = float(COST_LIMITS.get(self.limit_key, original_limit))  # type: ignore[arg-type]

        # Temporarily swap the limit so check_cost_budget uses the right cap
        COST_LIMITS["per_run_max"] = cap
        try:
            result = check_cost_budget(
                current_run_cost=self._run_cost,
                daily_total=self._daily(),
            )
        finally:
            COST_LIMITS["per_run_max"] = original_limit  # type: ignore[assignment]

        self._last_result = result

        if result["action"] == "HALT":
            raise CostLimitExceeded(
                f"[{agent_name}] Cost limit exceeded: " + "; ".join(result["warnings"]),
                action="HALT",
                warnings=result["warnings"],
            )

        return result

    def status(self) -> dict[str, Any]:
        """Current guard state — safe to call any time, raises nothing."""
        return {
            "run_cost":    self.run_cost,
            "daily_spend": round(self._daily(), 6),
            "last_check":  self._last_result,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _daily(self) -> float:
        if self._daily_spend is None:
            self._daily_spend = get_daily_spend(self.db_path)
        return self._daily_spend


# ---------------------------------------------------------------------------
# llm_call_guarded — drop-in replacement for llm_call()
# ---------------------------------------------------------------------------

def llm_call_guarded(
    client,
    tracker: TokenTracker | None,
    guard: CostGuard | None,
    agent: str,
    **kwargs,
) -> str:
    """llm_call() with optional CostGuard enforcement.

    Pre-call:  guard.check_before_call(agent) — raises CostLimitExceeded if HALT.
    Call:      llm_call(client, tracker, agent, **kwargs)
    Post-call: guard.sync_from_tracker(tracker) — keeps guard current.

    When guard is None, behaves identically to llm_call().
    When tracker is None, guard cannot sync (no-op sync).
    """
    if guard is not None:
        guard.check_before_call(agent)

    text = llm_call(client, tracker, agent, **kwargs)

    if guard is not None and tracker is not None:
        guard.sync_from_tracker(tracker)

    return text


# ---------------------------------------------------------------------------
# send_cost_alert — Teams MessageCard webhook
# ---------------------------------------------------------------------------

def send_cost_alert(
    webhook_url: str,
    alert_dict: dict[str, Any],
    timeout_s: int = 5,
) -> bool:
    """POST a Teams MessageCard to webhook_url.

    Card is red for HALT, orange for WARN, grey for PROCEED.
    Returns True on HTTP 200, False otherwise (never raises).

    Args:
        webhook_url: Incoming Webhook URL for the Teams channel.
        alert_dict:  Must contain keys:
                       action          — "HALT" | "WARN" | "PROCEED"
                       current_run_cost — float USD
                       daily_total      — float USD
                       warnings         — list[str]
                     Additional keys are included in a JSON facts section.
    """
    action = alert_dict.get("action", "UNKNOWN")

    color_map = {
        "HALT":    "FF0000",   # red
        "WARN":    "FF8C00",   # orange
        "PROCEED": "808080",   # grey
    }
    theme_color = color_map.get(action, "808080")

    run_cost   = alert_dict.get("current_run_cost", 0.0)
    daily_total = alert_dict.get("daily_total", 0.0)
    warnings   = alert_dict.get("warnings", [])

    facts = [
        {"name": "Action",        "value": action},
        {"name": "Run cost",      "value": f"${run_cost:.6f}"},
        {"name": "Daily total",   "value": f"${daily_total:.6f}"},
        {"name": "Per-run limit", "value": f"${float(COST_LIMITS['per_run_max']):.2f}"},
        {"name": "Daily limit",   "value": f"${float(COST_LIMITS['daily_max']):.2f}"},
    ]
    # Append any extra keys from alert_dict as additional facts
    reserved = {"action", "current_run_cost", "daily_total", "warnings"}
    for k, v in alert_dict.items():
        if k not in reserved:
            facts.append({"name": k, "value": str(v)})

    body_text = "\n\n".join(warnings) if warnings else "No specific warnings."

    card = {
        "@type":       "MessageCard",
        "@context":    "http://schema.org/extensions",
        "themeColor":  theme_color,
        "summary":     f"SAFe Pipeline Cost Alert — {action}",
        "sections": [
            {
                "activityTitle":    f"SAFe Feature Spec — Cost {action}",
                "activitySubtitle": "Spending limit notification",
                "activityText":     body_text,
                "facts":            facts,
            }
        ],
    }

    payload = json.dumps(card).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """
    Verifies PROCEED → WARN → HALT transitions and CostLimitExceeded semantics.
    Uses mock costs — no LLM calls, no DB writes.
    """
    import traceback

    PER_RUN  = float(COST_LIMITS["per_run_max"])   # 0.50
    DAILY    = float(COST_LIMITS["daily_max"])      # 5.00
    WARN_AT  = PER_RUN * _WARN_THRESHOLD            # 0.40
    HALT_AT  = PER_RUN                              # 0.50

    width = 60
    print("=" * width)
    print("  COST GUARDRAILS — smoke test")
    print("=" * width)
    failures: list[str] = []

    # ── 1. check_cost_budget transitions ─────────────────────────────────────
    print("\n[1] check_cost_budget transitions")

    cases = [
        ("PROCEED — well below limits",   0.10,  0.50,  "PROCEED"),
        ("WARN   — run cost at 85%",       0.43,  0.50,  "WARN"),
        ("WARN   — daily at 85%",          0.10,  4.10,  "WARN"),
        ("HALT   — run cost at 100%",      0.50,  0.50,  "HALT"),
        ("HALT   — daily at 100%",         0.10,  4.95,  "HALT"),
        ("HALT   — run cost over limit",   0.75,  0.50,  "HALT"),
    ]

    for label, run_cost, daily, expected in cases:
        result = check_cost_budget(run_cost, daily)
        ok = result["action"] == expected
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {label}")
        if not ok:
            failures.append(
                f"check_cost_budget({run_cost}, {daily}): "
                f"expected {expected}, got {result['action']}"
            )
        elif result["warnings"]:
            for w in result["warnings"]:
                print(f"         ↳ {w}")

    # ── 2. CostGuard accumulation and HALT raising ────────────────────────────
    print("\n[2] CostGuard.check_before_call() accumulation")

    guard = CostGuard(daily_spend=0.0)   # skip DB query

    # Manually advance run cost through the thresholds
    steps = [
        (0.10, "PROCEED"),
        (0.30, "WARN"),      # 0.40 total — exactly at warn boundary (>= 80%)
        (0.01, "WARN"),      # 0.41 total
        (0.08, "WARN"),      # 0.49 total — still below HALT
    ]

    for increment, expected_action in steps:
        guard.add_cost(increment)
        try:
            result = guard.check_before_call("test_agent")
            ok = result["action"] == expected_action
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] run_cost={guard.run_cost:.2f} → {result['action']}")
            if not ok:
                failures.append(
                    f"CostGuard at run_cost={guard.run_cost:.2f}: "
                    f"expected {expected_action}, got {result['action']}"
                )
        except CostLimitExceeded as exc:
            print(f"  [FAIL] Unexpected HALT at run_cost={guard.run_cost:.2f}: {exc}")
            failures.append(str(exc))

    # Now push over the HALT threshold
    print("\n[3] CostLimitExceeded raised at HALT threshold")
    guard.add_cost(0.02)  # 0.51 — over the 0.50 limit
    raised = False
    try:
        guard.check_before_call("test_agent")
    except CostLimitExceeded as exc:
        raised = True
        ok = exc.action == "HALT"
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] CostLimitExceeded raised  action={exc.action}")
        print(f"         ↳ {exc.args[0]}")
        if not ok:
            failures.append(f"CostLimitExceeded.action expected HALT, got {exc.action}")
    if not raised:
        failures.append("CostLimitExceeded was NOT raised at HALT threshold")
        print("  [FAIL] CostLimitExceeded was NOT raised")

    # ── 4. improvement_iterations_max ─────────────────────────────────────────
    print("\n[4] improvement_iterations_max")
    max_iter = int(COST_LIMITS["improvement_iterations_max"])
    print(f"  Configured limit: {max_iter} iterations")
    print(f"  [PASS] (enforcement is the caller's responsibility — value is accessible)")

    # ── 5. per_improvement_max via limit_key ──────────────────────────────────
    print("\n[5] CostGuard with limit_key='per_improvement_max'")
    imp_guard = CostGuard(daily_spend=0.0, limit_key="per_improvement_max")
    imp_max   = float(COST_LIMITS["per_improvement_max"])  # 0.25
    imp_guard.add_cost(imp_max * 0.85)  # above warn, below halt
    try:
        result = imp_guard.check_before_call("improver")
        ok = result["action"] == "WARN"
        print(f"  [{'PASS' if ok else 'FAIL'}] at 85% of per_improvement_max → {result['action']}")
        if not ok:
            failures.append(f"per_improvement_max WARN: got {result['action']}")
    except CostLimitExceeded as exc:
        print(f"  [FAIL] Unexpected HALT: {exc}")
        failures.append(str(exc))

    imp_guard.add_cost(imp_max * 0.20)  # push over halt
    try:
        imp_guard.check_before_call("improver")
        print("  [FAIL] CostLimitExceeded not raised for per_improvement_max")
        failures.append("CostLimitExceeded not raised for per_improvement_max")
    except CostLimitExceeded:
        print(f"  [PASS] CostLimitExceeded raised at per_improvement_max HALT")

    # ── 6. sync_from_tracker ─────────────────────────────────────────────────
    print("\n[6] sync_from_tracker round-trip")
    tracker = TokenTracker()
    tracker.record(
        agent="reviewer",
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    sync_guard = CostGuard(daily_spend=0.0)
    sync_guard.sync_from_tracker(tracker)
    expected_cost = tracker.total_cost_usd()
    ok = abs(sync_guard.run_cost - expected_cost) < 1e-8
    print(
        f"  [{'PASS' if ok else 'FAIL'}] tracker.total_cost_usd()={expected_cost:.6f} "
        f"synced to guard.run_cost={sync_guard.run_cost:.6f}"
    )
    if not ok:
        failures.append(f"sync_from_tracker mismatch: {expected_cost} vs {sync_guard.run_cost}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * width}")
    if failures:
        print(f"  RESULT: {len(failures)} failure(s)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: all checks passed")
    print("=" * width)

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    _smoke_test()
