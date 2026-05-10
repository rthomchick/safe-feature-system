# evaluation/smoke_test.py
# Smoke test for the Day 1 eval-pipeline deliverables.
#
# No API calls are made. Exercises:
#   1. DB initialization
#   2. PromptRegistry — register, idempotency, get, list_versions
#   3. TokenTracker   — record, summary, cost estimate
#   4. ResultStore    — save_run, get_run, get_token_usage, latest_scores
#   5. flush_to_db and round-trip query of token rows
#
# Run from the project root:
#   python -m evaluation.smoke_test            # SQLite (temp DB, default)
#   DATABASE_URL=<url> python -m evaluation.smoke_test --postgres  # PostgreSQL

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from evaluation.eval_db import init_db
from evaluation.prompt_registry import PromptRegistry
from evaluation.result_store import ResultStore
from evaluation.token_tracker import TokenTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_SYSTEM_PROMPT_V1 = (
    "You are a SAFe Feature specification reviewer at ServiceNow. "
    "Score specs against a 100-point rubric and return structured JSON."
)
MOCK_SYSTEM_PROMPT_V2 = (
    "You are a SAFe Feature specification reviewer at ServiceNow. "
    "Score specs against a 100-point rubric and return structured JSON. "
    "[v2: adds feature-type-aware guidance]"
)

MOCK_SCORECARD = {
    "total_score": 89,
    "sections": {
        "Feature Definition & Objective": {
            "max_points": 13,
            "score": 12,
            "criteria": {
                "Business Objective": {"max": 5, "score": 5, "note": ""},
                "Success Metrics":    {"max": 4, "score": 3, "note": "KPIs could be more specific."},
                "Target Audience":    {"max": 4, "score": 4, "note": ""},
            },
            "recommendations": "",
        },
        "User Stories & Acceptance Criteria": {
            "max_points": 20,
            "score": 16,
            "criteria": {
                "Story Format":      {"max": 8, "score": 6, "note": "Given/when/then structure incomplete."},
                "Acceptance Criteria": {"max": 8, "score": 7, "note": ""},
                "Edge Cases":        {"max": 4, "score": 3, "note": ""},
            },
            "recommendations": "Strengthen given/when/then structure on remaining stories.",
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(label: str) -> None:
    print(f"  [OK] {label}")


def _section(title: str) -> None:
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_db_init(db_path: Path | None) -> None:
    _section("1. DB initialization")
    init_db(db_path)
    _ok(f"DB initialized (path={db_path or 'PostgreSQL'})")

    # Calling init_db a second time must not raise (CREATE IF NOT EXISTS)
    init_db(db_path)
    _ok("Re-initialization is idempotent")


def test_prompt_registry(db_path: Path | None) -> str:
    _section("2. PromptRegistry")
    registry = PromptRegistry(db_path)

    # Register v1
    pid1 = registry.register(
        name="reviewer",
        agent="reviewer",
        system_prompt=MOCK_SYSTEM_PROMPT_V1,
    )
    _ok(f"Registered reviewer v1 — id: {pid1}")

    # Idempotency: same content → same id, no duplicate row
    pid1_again = registry.register(
        name="reviewer",
        agent="reviewer",
        system_prompt=MOCK_SYSTEM_PROMPT_V1,
    )
    assert pid1 == pid1_again, "Same content must return same id"
    _ok("Idempotency — same content returns same id")

    # Register v2 (different content → new id, version 2)
    pid2 = registry.register(
        name="reviewer",
        agent="reviewer",
        system_prompt=MOCK_SYSTEM_PROMPT_V2,
    )
    assert pid2 != pid1, "Different content must produce different id"
    _ok(f"Registered reviewer v2 — id: {pid2}")

    # get() by id
    fetched = registry.get(pid1)
    assert fetched is not None
    assert fetched["name"] == "reviewer"
    assert fetched["version"] == 1
    assert fetched["agent"] == "reviewer"
    _ok(f"get(pid1) → name={fetched['name']} version={fetched['version']}")

    # get_latest()
    latest = registry.get_latest("reviewer")
    assert latest is not None
    assert latest["version"] == 2
    _ok(f"get_latest('reviewer') → version={latest['version']}")

    # list_versions()
    versions = registry.list_versions("reviewer")
    assert len(versions) == 2
    assert versions[0]["version"] == 1
    assert versions[1]["version"] == 2
    _ok(f"list_versions('reviewer') → {[v['version'] for v in versions]}")

    # list_agents()
    agents = registry.list_agents()
    assert "reviewer" in agents
    _ok(f"list_agents() → {agents}")

    return pid1  # used in later tests


def test_token_tracker() -> TokenTracker:
    _section("3. TokenTracker")
    tracker = TokenTracker()

    tracker.record(agent="router",    model="claude-haiku-4-5-20251001",   input_tokens=120,  output_tokens=5)
    tracker.record(agent="generator", model="claude-sonnet-4-5-20250929",  input_tokens=2400, output_tokens=1800)
    tracker.record(agent="reviewer",  model="claude-sonnet-4-5-20250929",  input_tokens=3100, output_tokens=900)
    tracker.record(agent="improver",  model="claude-sonnet-4-5-20250929",  input_tokens=4200, output_tokens=2100)
    tracker.record(agent="reviewer",  model="claude-sonnet-4-5-20250929",  input_tokens=3000, output_tokens=850)

    totals = tracker.total_tokens()
    assert totals["calls"] == 5
    assert totals["input"]  == 120 + 2400 + 3100 + 4200 + 3000
    assert totals["output"] == 5 + 1800 + 900 + 2100 + 850
    _ok(f"total_tokens → input={totals['input']} output={totals['output']} calls={totals['calls']}")

    cost = tracker.total_cost_usd()
    assert cost > 0
    _ok(f"total_cost_usd → ${cost:.4f}")

    by_agent = tracker.by_agent()
    assert by_agent["reviewer"]["calls"] == 2
    assert by_agent["router"]["input"] == 120
    _ok(f"by_agent → reviewer has {by_agent['reviewer']['calls']} calls")

    summary = tracker.summary()
    assert "cost_usd" in summary
    assert "by_agent" in summary
    _ok("summary() includes cost_usd and by_agent")

    return tracker  # used in the flush test


def test_result_store_and_flush(
    db_path: Path | None, prompt_id: str, tracker: TokenTracker
) -> None:
    _section("4. ResultStore + token flush")
    store = ResultStore(db_path)

    # Save a run
    run_id = store.save_run(
        golden_set_id="cap_001",
        feature_type="CAPABILITY",
        scorecard=MOCK_SCORECARD,
        prompt_id=prompt_id,
        original_score=71,
        final_score=89,
        passed=True,
    )
    _ok(f"save_run → id: {run_id}")

    # Flush token records linked to this run
    tracker.flush_to_db(run_id, db_path)
    _ok("flush_to_db completed")

    # get_run round-trip
    run = store.get_run(run_id)
    assert run is not None
    assert run["golden_set_id"] == "cap_001"
    assert run["feature_type"] == "CAPABILITY"
    assert run["original_score"] == 71
    assert run["final_score"] == 89
    assert bool(run["passed"]) is True
    assert run["scorecard"]["total_score"] == 89
    assert "Feature Definition & Objective" in run["scorecard"]["sections"]
    _ok(f"get_run round-trip — score={run['final_score']} sections={list(run['scorecard']['sections'].keys())}")

    # get_token_usage
    usage = store.get_token_usage(run_id)
    assert len(usage) == 5
    agents_in_db = [r["agent"] for r in usage]
    assert agents_in_db.count("reviewer") == 2
    _ok(f"get_token_usage → {len(usage)} rows, agents: {agents_in_db}")

    # token_summary
    tsummary = store.token_summary(run_id)
    assert tsummary["calls"] == 5
    assert tsummary["by_agent"]["reviewer"]["calls"] == 2
    _ok(f"token_summary → calls={tsummary['calls']} cost re-derivable from rows")

    # get_runs_for_golden
    runs = store.get_runs_for_golden("cap_001")
    assert len(runs) >= 1
    assert any(r["id"] == run_id for r in runs)
    _ok(f"get_runs_for_golden('cap_001') → {len(runs)} run(s)")

    # latest_scores
    latest = store.latest_scores("cap_001")
    assert latest is not None
    assert latest["final_score"] == 89
    assert latest["passed"] is True
    _ok(f"latest_scores → final={latest['final_score']} passed={latest['passed']}")

    # Non-existent golden_set_id returns None
    assert store.latest_scores("does_not_exist") is None
    _ok("latest_scores for unknown id returns None")


# ---------------------------------------------------------------------------
# PostgreSQL cleanup helper
# ---------------------------------------------------------------------------

def _cleanup_postgres(prompt_id: str) -> None:
    """Remove test rows inserted into the shared PostgreSQL DB."""
    from evaluation.eval_db import get_connection
    with get_connection() as conn:
        # token_usage rows are deleted via FK cascade if REFERENCES eval_runs ON DELETE CASCADE,
        # but our schema doesn't have CASCADE, so delete in dependency order.
        conn.execute(
            "DELETE FROM token_usage WHERE run_id IN "
            "(SELECT id FROM eval_runs WHERE golden_set_id = 'cap_001')"
        )
        conn.execute("DELETE FROM eval_runs WHERE golden_set_id = 'cap_001'")
        conn.execute("DELETE FROM prompts WHERE name = 'reviewer'")
    print("  [OK] PostgreSQL test rows cleaned up")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(db_path: Path | None, postgres_mode: bool) -> None:
    backend = "PostgreSQL" if postgres_mode else f"SQLite ({db_path})"
    print(f"\n=== SAFe Eval Pipeline — Smoke Test ({backend}) ===")

    try:
        test_db_init(db_path)
        prompt_id = test_prompt_registry(db_path)
        tracker   = test_token_tracker()
        test_result_store_and_flush(db_path, prompt_id, tracker)

        print(f"\n{'=' * 55}")
        print("  ALL CHECKS PASSED")
        print(f"{'=' * 55}\n")

    finally:
        if postgres_mode:
            try:
                _cleanup_postgres(prompt_id)  # type: ignore[possibly-undefined]
            except Exception as exc:
                print(f"  [WARN] PG cleanup failed: {exc}")
        elif db_path is not None:
            db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Smoke test for the SAFe eval pipeline"
    )
    parser.add_argument(
        "--postgres",
        action="store_true",
        help="Run against the live PostgreSQL DB (DATABASE_URL must be set)",
    )
    args = parser.parse_args()

    if args.postgres:
        import os
        if not os.environ.get("DATABASE_URL"):
            raise SystemExit("ERROR: DATABASE_URL must be set for --postgres mode")
        run(db_path=None, postgres_mode=True)
    else:
        _tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        _tmp.close()
        run(db_path=Path(_tmp.name), postgres_mode=False)
