# evaluation/dashboard.py
# Streamlit eval dashboard — 5 tabs covering run execution, comparison,
# quality trends, cost tracking, and an improvement suggester placeholder.
#
# Run with:
#   python -m streamlit run evaluation/dashboard.py

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path when launched via streamlit run.
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic
import pandas as pd
import streamlit as st

from evaluation.eval_db import DEFAULT_DB_PATH, get_connection, init_db
from evaluation.golden_set import GOLDEN_SET
from evaluation.improvement_suggester import ImprovementSuggester
from evaluation.prompt_registry import PromptRegistry
from evaluation.result_store import ResultStore
from evaluation.token_tracker import _TOKEN_COSTS
import evaluation.eval_runner as eval_runner
from agents.router import ROUTER_SYSTEM_PROMPT_V2

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Eval Dashboard — SAFe Feature Spec",
    page_icon="📊",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Init DB + shared Anthropic client
# ---------------------------------------------------------------------------

init_db()


@st.cache_resource
def _get_anthropic_client() -> anthropic.Anthropic:
    """Create a single shared Anthropic client for the dashboard process."""
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return anthropic.Anthropic(api_key=api_key)

# ---------------------------------------------------------------------------
# DB query helpers
# ---------------------------------------------------------------------------

def _compute_cost(input_tokens: int, output_tokens: int, model: str) -> float:
    pricing = _TOKEN_COSTS.get(model, _TOKEN_COSTS["default"])
    return (
        (input_tokens  / 1_000_000) * pricing["input"] +
        (output_tokens / 1_000_000) * pricing["output"]
    )


@st.cache_data(ttl=15)
def load_all_runs() -> pd.DataFrame:
    """All eval_runs joined with prompt names, newest first."""
    with get_connection(DEFAULT_DB_PATH) as conn:
        rows = conn.execute("""
            SELECT
                er.id,  er.golden_set_id,  er.feature_type,
                er.classified_as,  er.run_at,
                er.original_score, er.final_score, er.passed,
                er.scorecard,
                COALESCE(p.name,  '—') AS prompt_name,
                COALESCE(rp.name, '—') AS router_prompt_name
            FROM eval_runs er
            LEFT JOIN prompts p  ON er.prompt_id        = p.id
            LEFT JOIN prompts rp ON er.router_prompt_id = rp.id
            ORDER BY er.run_at DESC
        """).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["run_at"]    = pd.to_datetime(df["run_at"])
    df["scorecard"] = df["scorecard"].apply(lambda s: json.loads(s) if s else {})
    df["passed"]    = df["passed"].map({1: True, 0: False, None: None})
    df["routing_correct"] = df.apply(
        lambda r: r["feature_type"] == r["classified_as"]
        if pd.notnull(r["classified_as"]) else None,
        axis=1,
    )
    return df


@st.cache_data(ttl=15)
def load_token_costs() -> pd.DataFrame:
    """One row per (run_id, agent, model): input_tokens, output_tokens, cost_usd."""
    with get_connection(DEFAULT_DB_PATH) as conn:
        rows = conn.execute("""
            SELECT run_id, agent, model,
                   SUM(input_tokens)  AS input_tokens,
                   SUM(output_tokens) AS output_tokens
            FROM token_usage
            GROUP BY run_id, agent, model
        """).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])
    df["cost_usd"] = df.apply(
        lambda r: _compute_cost(r["input_tokens"], r["output_tokens"], r["model"]),
        axis=1,
    )
    return df


def expand_sections(runs_df: pd.DataFrame) -> pd.DataFrame:
    """Expand scorecard JSON → one row per (run_id, golden_set_id, run_at, section)."""
    rows = []
    for _, r in runs_df.iterrows():
        sc = r.get("scorecard") or {}
        for sec_name, sec_data in sc.get("sections", {}).items():
            rows.append({
                "run_id":        r["id"],
                "golden_set_id": r["golden_set_id"],
                "run_at":        r["run_at"],
                "section":       sec_name,
                "score":         sec_data.get("score", 0),
                "max_points":    sec_data.get("max_points", 0),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_PASS_ICON   = {True: "✅", False: "❌", None: "—"}
_ROUTE_ICON  = {True: "✅", False: "❌", None: "—"}


def _pct_flag(pct: int) -> str:
    if pct < 60:
        return "🔴"
    if pct < 75:
        return "🟡"
    return "🟢"


def _delta_str(delta: int | float | None) -> str:
    if delta is None:
        return "—"
    if delta > 0:
        return f"▲ {int(delta)}"
    if delta < 0:
        return f"▼ {int(abs(delta))}"
    return "—"


def _run_label(row: pd.Series) -> str:
    ts = row["run_at"].strftime("%m-%d %H:%M") if pd.notnull(row["run_at"]) else "?"
    score = row["final_score"] if pd.notnull(row["final_score"]) else "?"
    return f"{row['golden_set_id']}  |  {ts}  |  {score}/100"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("📊 SAFe Feature Spec — Eval Dashboard")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "▶  Run Evaluation",
    "⚖  Compare Runs",
    "📈  Quality",
    "💰  Cost",
    "💡  Suggest Improvements",
])


# ===========================================================================
# TAB 1 — Run Evaluation
# ===========================================================================

with tab1:
    st.subheader("Run Evaluation")

    col_a, col_b = st.columns(2)
    with col_a:
        router_version = st.selectbox(
            "Router version",
            ["v1", "v2"],
            help="v1 = original prompt  |  v2 = improved EXPERIENCE classifier",
            key="t1_router",
        )
    with col_b:
        case_options = ["— all cases —"] + [
            f"{e['id']}  ({e['name']})" for e in GOLDEN_SET
        ]
        case_sel = st.selectbox("Case to run", case_options, key="t1_case")

    case_filter = (
        None if case_sel.startswith("—")
        else case_sel.split("  ")[0]
    )
    cases_to_run = (
        GOLDEN_SET if case_filter is None
        else [e for e in GOLDEN_SET if e["id"] == case_filter]
    )

    st.caption(
        f"Will run **{len(cases_to_run)}** case(s) with router **{router_version}**.  "
        "Each case calls router → generator → reviewer (~20–60s per case)."
    )

    if st.button("▶  Run", type="primary", key="t1_run_btn"):
        registry = PromptRegistry()
        store    = ResultStore()
        prompt_ids = eval_runner.register_baseline_prompts(registry)
        router_system_prompt = (
            ROUTER_SYSTEM_PROMPT_V2 if router_version == "v2" else None
        )

        progress     = st.progress(0.0, text="Starting…")
        run_results: list[dict] = []

        for i, entry in enumerate(cases_to_run):
            n = len(cases_to_run)
            progress.progress(i / n, text=f"Running {entry['id']}  ({i+1}/{n})…")
            try:
                result = eval_runner.run_case(
                    entry, prompt_ids, store,
                    router_system_prompt=router_system_prompt,
                )
                run_results.append(result)
            except Exception as exc:
                run_results.append({
                    "case_id": entry["id"],
                    "passed":  False,
                    "error":   str(exc),
                })

        progress.progress(1.0, text="Done!")
        st.session_state["t1_results"] = run_results
        st.cache_data.clear()   # flush DB caches so other tabs refresh

    # ── Results ──────────────────────────────────────────────────────────────

    if "t1_results" in st.session_state:
        results = st.session_state["t1_results"]

        # Summary table
        table_rows = []
        for r in results:
            if "error" in r:
                table_rows.append({
                    "Case": r["case_id"], "Type": "—", "Score": "ERROR",
                    "Min": "—", "Pass": "❌", "Routing": "—", "Cost": "—",
                })
            else:
                score_s = (
                    "PARSE ERR" if r.get("has_parse_error")
                    else f"{r['total_score']}/100"
                )
                table_rows.append({
                    "Case":    r["case_id"],
                    "Type":    r["feature_type"],
                    "Score":   score_s,
                    "Min":     r["expected_min"],
                    "Pass":    _PASS_ICON[r["passed"]],
                    "Routing": (
                        "✅" if r["routing_correct"]
                        else f"❌ →{r['classified_as']}"
                    ),
                    "Time (s)": r.get("elapsed_s", "—"),
                    "Cost":    f"${r['token_summary']['cost_usd']:.4f}",
                })

        st.dataframe(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
        )

        total_cost = sum(
            r.get("token_summary", {}).get("cost_usd", 0.0)
            for r in results if "error" not in r
        )
        passed_n  = sum(1 for r in results if r.get("passed"))
        total_n   = len(results)
        c1, c2, c3 = st.columns(3)
        c1.metric("Passed", f"{passed_n}/{total_n}")
        c2.metric("Total cost", f"${total_cost:.4f}")
        c3.metric("Cases run", total_n)

        # Per-case expandable scorecards
        st.subheader("Per-case scorecards")
        for r in results:
            if "error" in r:
                with st.expander(f"❌ {r['case_id']}  — ERROR"):
                    st.error(r["error"])
                continue

            icon  = "✅" if r["passed"] else "❌"
            score = r.get("total_score", "?")
            with st.expander(f"{icon}  {r['case_id']}  —  {score}/100"):
                sc = r.get("scorecard", {})
                if "parse_error" in sc:
                    st.error(f"Parse error: {sc['parse_error']}")
                else:
                    sec_rows = []
                    for sec_name, sec_data in sc.get("sections", {}).items():
                        s   = sec_data.get("score", 0)
                        mx  = sec_data.get("max_points", 0)
                        pct = round(s / mx * 100) if mx > 0 else 0
                        sec_rows.append({
                            "":           _pct_flag(pct),
                            "Section":    sec_name,
                            "Score":      f"{s}/{mx}",
                            "%":          pct,
                            "Recommendations": sec_data.get("recommendations", ""),
                        })
                    st.dataframe(
                        pd.DataFrame(sec_rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "": st.column_config.TextColumn(label="", width="small"),
                            "%": st.column_config.NumberColumn(format="%d %%"),
                        },
                    )


# ===========================================================================
# TAB 2 — Compare Runs
# ===========================================================================

with tab2:
    st.subheader("Compare Two Runs")
    runs_df = load_all_runs()

    if runs_df.empty:
        st.info("No runs stored yet. Run the evaluation first (Tab 1).")
    else:
        run_labels = {
            row["id"]: _run_label(row)
            for _, row in runs_df.iterrows()
        }
        run_ids = list(run_labels.keys())

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Run A**")
            run_a_id = st.selectbox(
                "Select run A",
                run_ids,
                format_func=lambda x: run_labels[x],
                key="cmp_a",
            )
        with col_b:
            st.markdown("**Run B**")
            default_b = min(1, len(run_ids) - 1)
            run_b_id = st.selectbox(
                "Select run B",
                run_ids,
                index=default_b,
                format_func=lambda x: run_labels[x],
                key="cmp_b",
            )

        if run_a_id == run_b_id:
            st.warning("Select two different runs.")
        else:
            row_a = runs_df[runs_df["id"] == run_a_id].iloc[0]
            row_b = runs_df[runs_df["id"] == run_b_id].iloc[0]

            # ── Metadata ──────────────────────────────────────────────────
            meta = pd.DataFrame([
                {"":  "Case",         "Run A": row_a["golden_set_id"],      "Run B": row_b["golden_set_id"]},
                {"":  "Type",         "Run A": row_a["feature_type"],        "Run B": row_b["feature_type"]},
                {"":  "Classified as","Run A": row_a["classified_as"] or "?","Run B": row_b["classified_as"] or "?"},
                {"":  "Router",       "Run A": row_a["router_prompt_name"],  "Run B": row_b["router_prompt_name"]},
                {"":  "Reviewer",     "Run A": row_a["prompt_name"],         "Run B": row_b["prompt_name"]},
                {"":  "Total score",  "Run A": row_a["final_score"],         "Run B": row_b["final_score"]},
                {"":  "Passed",       "Run A": _PASS_ICON[row_a["passed"]],  "Run B": _PASS_ICON[row_b["passed"]]},
            ])
            st.dataframe(meta, use_container_width=True, hide_index=True)

            # ── Section scores ────────────────────────────────────────────
            sc_a = row_a["scorecard"].get("sections", {})
            sc_b = row_b["scorecard"].get("sections", {})
            all_secs = sorted(set(list(sc_a.keys()) + list(sc_b.keys())))

            sec_rows = []
            for sec in all_secs:
                a_score = sc_a.get(sec, {}).get("score") if sec in sc_a else None
                b_score = sc_b.get(sec, {}).get("score") if sec in sc_b else None
                max_pts = (sc_a.get(sec) or sc_b.get(sec) or {}).get("max_points", 0)
                delta   = (b_score - a_score) if (a_score is not None and b_score is not None) else None
                sec_rows.append({
                    "Section":    sec,
                    "A":          a_score,
                    "B":          b_score,
                    "Max":        max_pts,
                    "Delta B−A":  _delta_str(delta),
                })

            st.markdown("**Section scores**")
            st.dataframe(
                pd.DataFrame(sec_rows),
                use_container_width=True,
                hide_index=True,
            )

            # ── Cost + metrics ────────────────────────────────────────────
            costs_df = load_token_costs()
            if not costs_df.empty:
                cost_a = costs_df[costs_df["run_id"] == run_a_id]["cost_usd"].sum()
                cost_b = costs_df[costs_df["run_id"] == run_b_id]["cost_usd"].sum()
                score_delta = int(
                    (row_b["final_score"] or 0) - (row_a["final_score"] or 0)
                )
                c1, c2, c3 = st.columns(3)
                c1.metric("Cost A", f"${cost_a:.4f}")
                c2.metric("Cost B", f"${cost_b:.4f}",
                          delta=f"${cost_b - cost_a:+.4f}")
                c3.metric("Score Δ (B−A)", f"{score_delta:+d}")

            # ── Promote winner ────────────────────────────────────────────
            st.divider()
            if st.button("Promote Winner", key="promote_btn"):
                score_a = int(row_a["final_score"] or 0)
                score_b = int(row_b["final_score"] or 0)
                if score_a == score_b:
                    st.info("Runs are tied — no clear winner to promote.")
                elif score_b > score_a:
                    st.success(
                        f"**Winner: Run B** — score {score_b} vs {score_a}  "
                        f"(reviewer: `{row_b['prompt_name']}`, "
                        f"router: `{row_b['router_prompt_name']}`).  "
                        "Full promotion logic coming Day 5."
                    )
                else:
                    st.success(
                        f"**Winner: Run A** — score {score_a} vs {score_b}  "
                        f"(reviewer: `{row_a['prompt_name']}`, "
                        f"router: `{row_a['router_prompt_name']}`).  "
                        "Full promotion logic coming Day 5."
                    )


# ===========================================================================
# TAB 3 — Quality Dashboard
# ===========================================================================

with tab3:
    st.subheader("Quality Dashboard")
    runs_df = load_all_runs()

    if runs_df.empty:
        st.info("No runs stored yet.")
    else:
        # ── Score over time ───────────────────────────────────────────────
        st.markdown("#### Score over time")
        score_df = (
            runs_df[["run_at", "golden_set_id", "final_score"]]
            .dropna(subset=["final_score"])
            .copy()
        )
        if not score_df.empty:
            pivot = score_df.pivot_table(
                index="run_at",
                columns="golden_set_id",
                values="final_score",
                aggfunc="mean",
            )
            st.line_chart(pivot)
        else:
            st.caption("No score data yet.")

        # ── Section score trend ───────────────────────────────────────────
        st.markdown("#### Section score trend")
        sec_df = expand_sections(runs_df)
        if not sec_df.empty:
            all_sections = sorted(sec_df["section"].unique())
            selected_section = st.selectbox(
                "Section", all_sections, key="t3_section"
            )
            sec_filtered = sec_df[sec_df["section"] == selected_section].copy()
            pivot_sec = sec_filtered.pivot_table(
                index="run_at",
                columns="golden_set_id",
                values="score",
                aggfunc="mean",
            )
            st.line_chart(pivot_sec)
        else:
            st.caption("No section data yet.")

        # ── Pass rate ─────────────────────────────────────────────────────
        st.markdown("#### Pass rate")
        total_n  = len(runs_df)
        passed_n = int(runs_df["passed"].sum())
        route_ok = int(runs_df["routing_correct"].sum()) if "routing_correct" in runs_df.columns else None

        c1, c2, c3 = st.columns(3)
        c1.metric("Pass rate",      f"{passed_n}/{total_n}")
        c2.metric("Routing accuracy", f"{route_ok}/{total_n}" if route_ok is not None else "—")
        c3.metric("Total runs",     total_n)

        # ── History table ─────────────────────────────────────────────────
        st.markdown("#### All runs")
        history = runs_df[[
            "golden_set_id", "feature_type", "classified_as", "routing_correct",
            "final_score", "passed", "prompt_name", "router_prompt_name", "run_at",
        ]].copy()
        history["passed"]          = history["passed"].map(_PASS_ICON)
        history["routing_correct"] = history["routing_correct"].map(
            {True: "✅", False: "❌", None: "—"}
        )
        history.columns = [
            "Case", "Type", "Classified as", "Routing",
            "Score", "Passed", "Reviewer prompt", "Router prompt", "Run at",
        ]
        st.dataframe(history, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 4 — Cost Tracker
# ===========================================================================

with tab4:
    st.subheader("Cost Tracker")
    costs_df = load_token_costs()
    runs_df4 = load_all_runs()

    if costs_df.empty or runs_df4.empty:
        st.info("No cost data yet. Run the evaluation first.")
    else:
        # Aggregate per run
        per_run = (
            costs_df.groupby("run_id")["cost_usd"]
            .sum()
            .reset_index()
            .rename(columns={"cost_usd": "cost"})
        )
        per_run = per_run.merge(
            runs_df4[["id", "golden_set_id", "run_at"]].rename(columns={"id": "run_id"}),
            on="run_id",
            how="left",
        ).sort_values("run_at")

        # ── Summary metrics ───────────────────────────────────────────────
        avg_cost   = per_run["cost"].mean()
        total_cost = per_run["cost"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total spend",    f"${total_cost:.4f}")
        c2.metric("Avg cost / run", f"${avg_cost:.4f}")
        c3.metric("Total runs",     len(per_run))

        # ── Cost per run bar chart ────────────────────────────────────────
        st.markdown("#### Cost per run")
        bar_df = (
            per_run
            .set_index("golden_set_id")[["cost"]]
            .rename(columns={"cost": "Cost (USD)"})
        )
        st.bar_chart(bar_df)

        # ── Per-agent cost breakdown ───────────────────────────────────────
        st.markdown("#### Cost by agent")
        agent_costs = (
            costs_df
            .groupby("agent")[["input_tokens", "output_tokens", "cost_usd"]]
            .sum()
            .reset_index()
            .sort_values("cost_usd", ascending=False)
        )
        agent_costs.columns = ["Agent", "Input tokens", "Output tokens", "Cost (USD)"]
        st.dataframe(agent_costs, use_container_width=True, hide_index=True)

        # Stacked agent cost chart (one bar per agent)
        st.markdown("#### Cost by agent (chart)")
        agent_chart = (
            costs_df
            .groupby("agent")["cost_usd"]
            .sum()
            .reset_index()
            .set_index("agent")
            .rename(columns={"cost_usd": "Cost (USD)"})
        )
        st.bar_chart(agent_chart)

        # ── Cumulative cost over time ─────────────────────────────────────
        st.markdown("#### Cumulative spend over time")
        cum_df = per_run.sort_values("run_at").copy()
        cum_df["Cumulative cost (USD)"] = cum_df["cost"].cumsum()
        cum_df = cum_df.set_index("run_at")[["Cumulative cost (USD)"]]
        st.line_chart(cum_df)

        # ── Detailed cost table ───────────────────────────────────────────
        st.markdown("#### Cost detail by run")
        detail = per_run[["golden_set_id", "run_at", "cost"]].copy()
        detail.columns = ["Case", "Run at", "Cost (USD)"]
        detail["Cost (USD)"] = detail["Cost (USD)"].map(lambda x: f"${x:.4f}")
        st.dataframe(detail, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 5 — Suggest Improvements
# ===========================================================================

with tab5:
    st.subheader("Suggest Improvements")
    st.caption(
        "Analyzes stored eval runs for a case, finds the weakest sections, "
        "and asks Claude Sonnet to propose specific edits to the generator prompt. "
        "Advisory only — you decide whether to apply the suggestions."
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    col_case, col_n = st.columns([3, 1])
    with col_case:
        case_ids = [e["id"] for e in GOLDEN_SET]
        case_names = {e["id"]: e["name"] for e in GOLDEN_SET}
        selected_case = st.selectbox(
            "Golden-set case",
            case_ids,
            format_func=lambda x: f"{x}  ({case_names.get(x, '')})",
            key="t5_case",
        )
    with col_n:
        n_sections = st.number_input(
            "Sections to analyze",
            min_value=1, max_value=8, value=3, step=1,
            key="t5_n",
        )

    # Cache key: invalidate when a new run for this case is stored
    runs_for_case = load_all_runs()
    n_runs_for_case = (
        len(runs_for_case[runs_for_case["golden_set_id"] == selected_case])
        if not runs_for_case.empty else 0
    )

    if n_runs_for_case == 0:
        st.warning(
            f"No eval runs stored for **{selected_case}** yet. "
            "Run the evaluation first (Tab 1)."
        )
    else:
        st.caption(f"{n_runs_for_case} run(s) available for analysis.")

        if st.button("🔍 Analyze", type="primary", key="t5_analyze"):
            cache_key = f"t5_suggestions_{selected_case}_{n_runs_for_case}"
            # Invalidate stale cache if case or run count changed
            if st.session_state.get("t5_cache_key") != cache_key:
                st.session_state.pop("t5_suggestions", None)
            st.session_state["t5_cache_key"] = cache_key

            if "t5_suggestions" not in st.session_state:
                store    = ResultStore()
                registry = PromptRegistry()
                client   = _get_anthropic_client()
                suggester = ImprovementSuggester(store, registry, client)

                with st.spinner(
                    f"Analyzing {n_sections} weak section(s) for {selected_case}… "
                    "(1 Claude Sonnet call per section)"
                ):
                    suggestions = suggester.suggest(selected_case, n_sections=int(n_sections))

                st.session_state["t5_suggestions"] = suggestions

    # ── Results ────────────────────────────────────────────────────────────────
    if "t5_suggestions" in st.session_state and st.session_state.get("t5_cache_key", "").startswith(f"t5_suggestions_{selected_case}_"):
        suggestions = st.session_state["t5_suggestions"]

        if not suggestions:
            st.info("No section data found — check that scorecards parsed without errors.")
        else:
            st.divider()
            st.markdown(f"### Results for `{selected_case}`")

            for i, s in enumerate(suggestions, start=1):
                pct   = s.avg_pct
                flag  = _pct_flag(int(pct))
                score_label = f"{s.avg_score}/{s.avg_max} avg  ({pct:.0f}%)  across {s.n_runs} run(s)"

                with st.expander(
                    f"{flag}  **#{i} — {s.section_name}** — {score_label}",
                    expanded=True,
                ):
                    # ── Reviewer feedback ──────────────────────────────────
                    st.markdown("**Aggregated reviewer feedback**")
                    st.info(s.aggregated_feedback)

                    # ── Quote from current prompt ──────────────────────────
                    st.markdown("**Relevant text in current generator prompt**")
                    quote_text = s.quote or "(not parsed — see raw response below)"
                    st.markdown(f"> {quote_text.replace(chr(10), '  \n> ')}")

                    # ── Diagnosis ─────────────────────────────────────────
                    if s.diagnosis:
                        st.markdown("**Diagnosis**")
                        st.markdown(s.diagnosis)

                    # ── Suggested edit ─────────────────────────────────────
                    st.markdown("**Suggested prompt edit**")
                    if s.suggested_edit:
                        st.code(s.suggested_edit, language="diff")
                    else:
                        st.code(s.raw_response, language="text")

                    # ── Rationale ─────────────────────────────────────────
                    if s.rationale:
                        st.markdown("**Rationale**")
                        st.caption(s.rationale)

                    # ── Raw fallback ───────────────────────────────────────
                    if s.suggested_edit and s.raw_response:
                        with st.expander("Full Claude response (raw)", expanded=False):
                            st.text(s.raw_response)
