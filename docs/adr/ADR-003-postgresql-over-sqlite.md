# ADR-003: PostgreSQL over SQLite for Evaluation Storage

**Status:** Accepted
**Date:** 2026-04
**Repo:** safe-feature-system
**Decider:** Richard Thomchick

## Context

The evaluation pipeline initially used SQLite via a local file
(`evaluation/eval.db`) for storing prompt registry entries, eval runs,
token usage, and audit trail records. This worked for single-process local
development but failed when the system expanded to multiple surfaces:

- The Streamlit dashboard and the eval runner both write to the eval DB;
  SQLite's file locking caused write contention when both ran concurrently
- Streamlit Cloud (production deployment) does not provide persistent local
  file storage — the SQLite file was lost on every dyno restart, wiping
  eval history
- The intake copilot added a third write surface (Supabase persistence for
  intake requests), establishing a pattern of cloud-hosted relational
  storage that the eval DB should match

## Decision

Migrate eval storage to PostgreSQL hosted on Supabase, with a compatibility
wrapper (`evaluation/eval_db.py: _PgConn`) that provides a sqlite3-compatible
interface over psycopg2. Local development continues to use SQLite via the
same interface when `DATABASE_URL` is not set.

## Rationale

- Eliminates write contention — PostgreSQL handles concurrent writers
  correctly
- Eval history persists across Streamlit Cloud restarts
- `_PgConn` wrapper preserves the existing `execute() / commit() / rollback()`
  call pattern — no changes required in any module that uses the DB connection
- Dual-mode behavior (`DATABASE_URL` present → PostgreSQL; absent → SQLite)
  keeps local dev lightweight with no external dependency
- Consistent with Supabase already used for intake copilot persistence —
  single hosted database rather than two separate storage systems

## Consequences

- Production requires `DATABASE_URL` environment variable set in Streamlit
  Cloud secrets
- Local dev SQLite and production PostgreSQL can diverge in schema if
  migrations are not applied to both — risk mitigated by running schema
  init on every startup
- `_PgConn` wrapper must be kept in sync with any new sqlite3 methods used
  elsewhere in the codebase
- Direct PostgreSQL connection (port 5432) fails with IPv6 routing on
  Supabase; always use the pooler connection string (port 6543)
