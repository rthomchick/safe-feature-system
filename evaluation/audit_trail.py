"""
evaluation/audit_trail.py

Per-run decision trace for the SAFe Feature Spec pipeline.

Every significant pipeline decision — routing, generation, review, cost checks —
is logged as a timestamped event in the audit_trail table. The full ordered
trace for any run can be retrieved with get_trace(run_id).

Integration pattern (all three observability objects are optional):

    run_id  = str(uuid.uuid4())
    tracker = TokenTracker()
    guard   = CostGuard()
    trail   = AuditTrail()

    trail.log_event(run_id, ROUTE, {"input_description": desc,
                                     "classified_as": "CAPABILITY",
                                     "confidence": "high"})

    trail.log_event(run_id, COST_CHECK, {
        **guard.check_before_call("generator"),   # returns action + warnings
        "agent": "generator",
    })

CLI:
    python -m evaluation.audit_trail --run-id <id>   # print trace for one run
    python -m evaluation.audit_trail --list           # recent run IDs with timestamps
    python -m evaluation.audit_trail                  # run smoke test
"""

from __future__ import annotations

import argparse
import json
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.eval_db import get_connection, init_db, is_postgres, DEFAULT_DB_PATH


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------

ROUTE:        str = "ROUTE"         # Router classified the feature type
DRAFT:        str = "DRAFT"         # Draft Answerer produced section answers
GENERATE:     str = "GENERATE"      # Generator produced the spec
GROUND_CHECK: str = "GROUND_CHECK"  # Grounding / hallucination check (future)
REVIEW:       str = "REVIEW"        # Reviewer scored the spec
IMPROVE:      str = "IMPROVE"       # Improver applied a targeted edit pass
COST_CHECK:   str = "COST_CHECK"    # CostGuard evaluated spend limits

ALL_EVENT_TYPES: tuple[str, ...] = (
    ROUTE, DRAFT, GENERATE, GROUND_CHECK, REVIEW, IMPROVE, COST_CHECK,
)

# Canonical details_dict keys per event type — for documentation and validation
EVENT_SCHEMAS: dict[str, list[str]] = {
    ROUTE:        ["input_description", "classified_as", "confidence"],
    DRAFT:        ["sections_produced", "section_names"],
    GENERATE:     ["feature_type", "section_count", "output_length_chars"],
    GROUND_CHECK: ["checked", "flagged_claims", "result"],
    REVIEW:       ["total_score", "max_score", "weak_sections", "passed"],
    IMPROVE:      ["iteration", "sections_targeted", "score_before", "score_after"],
    COST_CHECK:   ["agent", "run_cost", "daily_total", "action", "warnings"],
}


# ---------------------------------------------------------------------------
# AuditTrail
# ---------------------------------------------------------------------------

class AuditTrail:
    """Writes and reads the audit_trail table for one or many pipeline runs.

    Thread-safety: each log_event() call opens and closes its own connection,
    which is safe for SQLite's WAL mode and fine for the sequential pipeline.

    Args:
        db_path: Path to the eval SQLite DB. Defaults to evaluation/eval.db.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def log_event(
        self,
        run_id: str,
        event_type: str,
        details_dict: dict[str, Any],
    ) -> int:
        """Append one event to the trace for run_id.

        Args:
            run_id:       UUID string matching an eval_runs.id row.
            event_type:   One of the module-level constants (ROUTE, REVIEW, …).
            details_dict: Event-specific payload; see EVENT_SCHEMAS for keys.

        Returns:
            The AUTOINCREMENT id of the inserted row (useful for tests).
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        payload = json.dumps(details_dict, default=str)

        with get_connection(self.db_path) as conn:
            if is_postgres(self.db_path):
                cur = conn.execute(
                    """INSERT INTO audit_trail (run_id, event_type, timestamp, details_json)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (run_id, event_type, ts, payload),
                )
                return cur.fetchone()["id"]
            else:
                cur = conn.execute(
                    """INSERT INTO audit_trail (run_id, event_type, timestamp, details_json)
                       VALUES (?, ?, ?, ?)""",
                    (run_id, event_type, ts, payload),
                )
                return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_trace(self, run_id: str) -> list[dict[str, Any]]:
        """Return all events for run_id, ordered by (timestamp, id).

        Each entry is:
            {
                "id":          int,
                "run_id":      str,
                "event_type":  str,
                "timestamp":   str,   # ISO-8601
                "details":     dict,  # deserialized from details_json
            }
        """
        ph = "%s" if is_postgres(self.db_path) else "?"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""SELECT id, run_id, event_type, timestamp, details_json
                   FROM   audit_trail
                   WHERE  run_id = {ph}
                   ORDER  BY timestamp ASC, id ASC""",
                (run_id,),
            ).fetchall()

        return [
            {
                "id":         r["id"],
                "run_id":     r["run_id"],
                "event_type": r["event_type"],
                "timestamp":  r["timestamp"],
                "details":    json.loads(r["details_json"]),
            }
            for r in rows
        ]

    def list_recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent run IDs that have audit events.

        Each entry: {"run_id": str, "first_event": str, "last_event": str,
                     "event_count": int}
        """
        ph = "%s" if is_postgres(self.db_path) else "?"
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""SELECT   run_id,
                            MIN(timestamp) AS first_event,
                            MAX(timestamp) AS last_event,
                            COUNT(*)       AS event_count
                   FROM     audit_trail
                   GROUP BY run_id
                   ORDER BY MAX(timestamp) DESC
                   LIMIT    {ph}""",
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CLI pretty-printer
# ---------------------------------------------------------------------------

_WIDTH = 70

# Short labels to distinguish event types visually
_EVENT_ICONS: dict[str, str] = {
    ROUTE:        "→ ROUTE       ",
    DRAFT:        "✎ DRAFT       ",
    GENERATE:     "⚙ GENERATE    ",
    GROUND_CHECK: "⚑ GROUND_CHECK",
    REVIEW:       "★ REVIEW      ",
    IMPROVE:      "↑ IMPROVE     ",
    COST_CHECK:   "$ COST_CHECK  ",
}


def _format_details(details: dict[str, Any], indent: int = 4) -> str:
    """Render details dict as indented key: value lines, wrapping long values."""
    pad = " " * indent
    lines: list[str] = []
    for k, v in details.items():
        if isinstance(v, list):
            lines.append(f"{pad}{k}: [{', '.join(str(x) for x in v)}]")
        elif isinstance(v, str) and len(v) > 60:
            wrapped = textwrap.fill(v, width=_WIDTH - indent - len(k) - 2,
                                    subsequent_indent=pad + " " * (len(k) + 2))
            lines.append(f"{pad}{k}: {wrapped}")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(lines)


def print_trace(run_id: str, trail: AuditTrail) -> None:
    events = trail.get_trace(run_id)
    print("=" * _WIDTH)
    print(f"  AUDIT TRAIL — run_id: {run_id}")
    print(f"  {len(events)} event(s)")
    print("=" * _WIDTH)

    if not events:
        print("  (no events recorded for this run)")
        return

    for i, ev in enumerate(events, 1):
        icon  = _EVENT_ICONS.get(ev["event_type"], f"  {ev['event_type']:<13}")
        ts    = ev["timestamp"]
        print(f"\n  [{i:02d}] {icon}  {ts}")
        formatted = _format_details(ev["details"])
        if formatted:
            print(formatted)

    print(f"\n{'=' * _WIDTH}")


def print_run_list(trail: AuditTrail) -> None:
    runs = trail.list_recent_runs()
    print("=" * _WIDTH)
    print("  RECENT RUNS WITH AUDIT EVENTS")
    print("=" * _WIDTH)

    if not runs:
        print("  (no audit events recorded yet)")
        return

    print(f"\n  {'RUN ID':<38} {'EVENTS':>6}  {'FIRST':>19}  {'LAST':>19}")
    print(f"  {'-' * 64}")
    for r in runs:
        print(
            f"  {r['run_id']:<38} {r['event_count']:>6}  "
            f"{r['first_event']:>19}  {r['last_event']:>19}"
        )
    print()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

def _smoke_test() -> None:
    """Creates a mock run with 4 events, retrieves and verifies the trace."""
    import tempfile

    print("=" * _WIDTH)
    print("  AUDIT TRAIL — smoke test")
    print("=" * _WIDTH)

    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_audit.db"
        init_db(db_path)

        # We need a real eval_runs row for the FK constraint.
        # The audit_trail smoke test always uses a temp SQLite path, so ? placeholders are safe.
        with get_connection(db_path) as conn:
            run_id = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO eval_runs
                   (id, golden_set_id, feature_type, original_score,
                    final_score, passed, scorecard)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (run_id, "cap_001_bare", "CAPABILITY", 71, 71, 1, "{}"),
            )

        trail = AuditTrail(db_path=db_path)

        # ── Log 4 events ─────────────────────────────────────────────────────
        print(f"\n  run_id: {run_id[:16]}…")

        e1 = trail.log_event(run_id, ROUTE, {
            "input_description": "Build a buying group identification capability.",
            "classified_as":     "CAPABILITY",
            "confidence":        "high",
        })
        print(f"  [1] logged {ROUTE}   → row id={e1}")

        e2 = trail.log_event(run_id, GENERATE, {
            "feature_type":        "CAPABILITY",
            "section_count":       8,
            "output_length_chars": 3200,
        })
        print(f"  [2] logged {GENERATE} → row id={e2}")

        e3 = trail.log_event(run_id, COST_CHECK, {
            "agent":       "reviewer",
            "run_cost":    0.12,
            "daily_total": 0.87,
            "action":      "PROCEED",
            "warnings":    [],
        })
        print(f"  [3] logged {COST_CHECK} → row id={e3}")

        e4 = trail.log_event(run_id, REVIEW, {
            "total_score":   71,
            "max_score":     100,
            "weak_sections": ["Acceptance Criteria", "Non-functional Requirements"],
            "passed":        True,
        })
        print(f"  [4] logged {REVIEW}  → row id={e4}")

        # ── Retrieve and verify ───────────────────────────────────────────────
        print("\n  Retrieving trace …")
        trace = trail.get_trace(run_id)

        # 4a. Correct count
        ok = len(trace) == 4
        print(f"  [{'PASS' if ok else 'FAIL'}] trace has {len(trace)} events (expected 4)")
        if not ok:
            failures.append(f"trace length: {len(trace)} != 4")

        # 4b. Correct order by insertion (all same second, ordered by id)
        expected_order = [ROUTE, GENERATE, COST_CHECK, REVIEW]
        actual_order   = [ev["event_type"] for ev in trace]
        ok = actual_order == expected_order
        print(f"  [{'PASS' if ok else 'FAIL'}] event order: {actual_order}")
        if not ok:
            failures.append(f"order: {actual_order} != {expected_order}")

        # 4c. ROUTE details intact
        route_ev = trace[0]
        ok = (
            route_ev["details"]["classified_as"] == "CAPABILITY"
            and route_ev["details"]["confidence"] == "high"
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] ROUTE details: classified_as={route_ev['details'].get('classified_as')} confidence={route_ev['details'].get('confidence')}")
        if not ok:
            failures.append(f"ROUTE details wrong: {route_ev['details']}")

        # 4d. REVIEW weak_sections is a list
        review_ev = trace[3]
        ok = isinstance(review_ev["details"]["weak_sections"], list) and \
             len(review_ev["details"]["weak_sections"]) == 2
        print(f"  [{'PASS' if ok else 'FAIL'}] REVIEW weak_sections={review_ev['details'].get('weak_sections')}")
        if not ok:
            failures.append(f"REVIEW weak_sections wrong: {review_ev['details']}")

        # 4e. COST_CHECK action is PROCEED
        cost_ev = trace[2]
        ok = cost_ev["details"]["action"] == "PROCEED"
        print(f"  [{'PASS' if ok else 'FAIL'}] COST_CHECK action={cost_ev['details'].get('action')}")
        if not ok:
            failures.append(f"COST_CHECK action wrong: {cost_ev['details']}")

        # 4f. list_recent_runs returns this run
        runs = trail.list_recent_runs()
        ok = any(r["run_id"] == run_id for r in runs)
        print(f"  [{'PASS' if ok else 'FAIL'}] list_recent_runs includes this run_id")
        if not ok:
            failures.append("list_recent_runs did not include the test run_id")

        # ── Print the trace for visual inspection ─────────────────────────────
        print()
        print_trace(run_id, trail)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("=" * _WIDTH)
    if failures:
        print(f"  RESULT: {len(failures)} failure(s)")
        for f in failures:
            print(f"    ✗ {f}")
    else:
        print("  RESULT: all checks passed")
    print("=" * _WIDTH)

    raise SystemExit(1 if failures else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Audit trail viewer for the SAFe Feature Spec eval pipeline"
    )
    parser.add_argument(
        "--run-id",
        metavar="ID",
        help="Print the ordered event trace for this run ID",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List recent run IDs that have audit events",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to the eval SQLite DB (default: evaluation/eval.db)",
    )
    args = parser.parse_args()

    if not args.run_id and not args.list:
        # No flags → run smoke test
        _smoke_test()

    init_db(Path(args.db))
    trail = AuditTrail(db_path=Path(args.db))

    if args.list:
        print_run_list(trail)
    elif args.run_id:
        print_trace(args.run_id, trail)
