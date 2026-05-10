"""
pages/request_queue.py

Request Queue — alternative entry point for the SAFe Feature Spec pipeline.

Three sections:
  1. Create Request — submit a new feature request to the queue
  2. Pending Requests — requests with status "ready"; click Process to run the pipeline
  3. Completed Requests — specs that have finished processing, with scores and costs

When a PM clicks Process:
  - Request data is loaded into session state (same fields the pipeline expects)
  - Status is set to "processing"
  - App switches to app.py at the "draft" stage, which runs the pipeline normally
  - On completion (stage_final in app.py), results are written back via the connector
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import streamlit as st

# Ensure project root is on sys.path when launched standalone.
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.router import classify_feature
from connectors.base import FeatureRequest
from connectors.postgres import PostgresConnector
from evaluation.audit_trail import AuditTrail
from evaluation.cost_guardrails import CostGuard
from evaluation.eval_db import init_db
from evaluation.result_store import ResultStore
from evaluation.token_tracker import TokenTracker

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Request Queue — SAFe Feature Spec",
    page_icon="📥",
    layout="wide",
)

# ── Bootstrap shared state ────────────────────────────────────────────────────
init_db()

if "connector" not in st.session_state:
    st.session_state.connector = PostgresConnector()

connector: PostgresConnector = st.session_state.connector

# ── Helpers ───────────────────────────────────────────────────────────────────

FEATURE_TYPE_OPTIONS = ["Auto-detect", "CAPABILITY", "EXPERIENCE", "WEBPAGE"]
TYPE_DESCRIPTIONS = {
    "CAPABILITY": "Backend tools, APIs, integrations, reusable engines",
    "EXPERIENCE": "UI components, interactive frontend features",
    "WEBPAGE":    "New pages or updates to existing pages on servicenow.com",
}
STATUS_EMOJI = {
    "draft":      "📝",
    "ready":      "🟢",
    "processing": "⚙️",
    "complete":   "✅",
    "failed":     "❌",
}


def _init_pipeline_run() -> None:
    """Bootstrap a fresh pipeline run into session state."""
    run_id = str(uuid.uuid4())
    st.session_state.run_id = run_id
    st.session_state.tracker = TokenTracker()
    st.session_state.trail = AuditTrail()
    st.session_state.guard = CostGuard()
    st.session_state._tracker_flushed = False
    st.session_state._connector_written = False
    store = ResultStore()
    store.save_run(
        golden_set_id="production",
        feature_type="UNKNOWN",
        scorecard={},
        run_id=run_id,
        original_score=0,
        final_score=0,
        passed=None,
    )


def _process_request(req: FeatureRequest) -> None:
    """Load a request into session state and redirect to the pipeline."""
    # Reset pipeline-specific state (preserve connector)
    pipeline_keys = [
        "stage", "feature_type", "notes", "description", "section_answers",
        "spec", "scorecard", "improved_spec", "improved_scorecard",
        "additional_context", "run_id", "tracker", "guard", "trail",
        "_tracker_flushed", "connector_request_id", "_connector_written",
    ]
    for key in pipeline_keys:
        if key in st.session_state:
            del st.session_state[key]

    # Load request data
    st.session_state.description = req.description
    st.session_state.notes = req.notes
    st.session_state.section_answers = {}
    st.session_state.additional_context = dict(req.boost_inputs) if req.boost_inputs else {}
    st.session_state.connector_request_id = req.id
    st.session_state.stage = "draft"

    # Classify feature type if not already set on the request
    _init_pipeline_run()
    with st.spinner("Classifying feature type..."):
        feature_type = req.feature_type or classify_feature(
            req.description, tracker=st.session_state.tracker
        )
    st.session_state.feature_type = feature_type

    # Mark as processing before handing off
    connector.update_status(req.id, "processing")

    st.switch_page("app.py")


# ═════════════════════════════════════════════════════════════════════════════
# PAGE LAYOUT
# ═════════════════════════════════════════════════════════════════════════════
st.title("📥 Request Queue")
st.caption(
    "Create and manage feature requests. Click **Process** to run the spec "
    "pipeline on any ready request."
)

# ── Sidebar refresh ───────────────────────────────────────────────────────────
if st.sidebar.button("🔄 Refresh lists"):
    st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1: CREATE REQUEST
# ═════════════════════════════════════════════════════════════════════════════
with st.expander("➕ Create New Request", expanded=True):
    with st.form("create_request_form", clear_on_submit=True):
        title = st.text_input(
            "Title *",
            placeholder="e.g. AI-powered buying group identification",
        )
        description = st.text_area(
            "Feature description *",
            placeholder=(
                "Describe the feature in one paragraph. This is what the router "
                "and generator will use."
            ),
            height=100,
        )
        notes = st.text_area(
            "Notes / context",
            placeholder=(
                "Meeting notes, Slack threads, strategy docs, requirements — "
                "anything you have. More context = better spec."
            ),
            height=150,
        )

        col1, col2 = st.columns(2)
        with col1:
            ft_choice = st.selectbox(
                "Feature type",
                options=FEATURE_TYPE_OPTIONS,
                help="Leave as Auto-detect to let the router classify it.",
            )
        with col2:
            start_status = st.selectbox(
                "Initial status",
                options=["ready", "draft"],
                help="'ready' means it appears in the Pending list immediately.",
            )

        boost_raw = st.text_area(
            "Boost inputs (JSON, optional)",
            value="{}",
            height=80,
            help=(
                'Pre-fill boost context for specific rubric sections. '
                'e.g. {"SEO, SEM, Analytics": "Target keywords: ...", '
                '"Feature Definition & Objective": "Owner: Jane, PM: Bob"}'
            ),
        )

        submitted = st.form_submit_button("Create Request", type="primary")

    if submitted:
        if not title.strip() or not description.strip():
            st.error("Title and description are required.")
        else:
            try:
                boost = json.loads(boost_raw) if boost_raw.strip() else {}
            except json.JSONDecodeError as exc:
                st.error(f"Boost inputs must be valid JSON: {exc}")
                boost = None

            if boost is not None:
                req = FeatureRequest(
                    id=str(uuid.uuid4()),
                    title=title.strip(),
                    description=description.strip(),
                    notes=notes.strip(),
                    feature_type=None if ft_choice == "Auto-detect" else ft_choice,
                    status=start_status,
                    boost_inputs=boost,
                )
                rid = connector.create_request(req)
                st.success(f"✅ Request created — ID: `{rid}`")
                st.rerun()

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2: PENDING REQUESTS
# ═════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("🟢 Pending Requests")
st.caption("Requests with status **ready** — click Process to run the spec pipeline.")

pending = connector.list_pending()

if not pending:
    st.info("No pending requests. Create one above or mark a draft as ready.")
else:
    for req in pending:
        with st.container(border=True):
            col1, col2, col3 = st.columns([4, 2, 1])

            with col1:
                ft_label = req.feature_type or "auto-detect"
                st.markdown(f"**{req.title}**")
                st.caption(
                    f"`{req.id[:16]}…`  •  type: {ft_label}"
                    + (f"  •  {len(req.boost_inputs)} boost section(s)" if req.boost_inputs else "")
                )

            with col2:
                if req.description:
                    st.caption(req.description[:120] + ("…" if len(req.description) > 120 else ""))

            with col3:
                if st.button("▶ Process", key=f"process_{req.id}", type="primary"):
                    _process_request(req)

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3: COMPLETED REQUESTS
# ═════════════════════════════════════════════════════════════════════════════
st.divider()
st.subheader("✅ Completed Requests")
st.caption("Most recent 20 completed specs.")

completed = connector.list_completed(limit=20)

if not completed:
    st.info("No completed requests yet.")
else:
    for req in completed:
        grade = (
            "A" if (req.score or 0) >= 90
            else "B" if (req.score or 0) >= 80
            else "C" if (req.score or 0) >= 70
            else "D"
        )
        ft_label = req.feature_type or "—"
        completed_str = (
            req.completed_at.strftime("%Y-%m-%d %H:%M") if req.completed_at else "—"
        )
        cost_str = f"${req.run_cost:.4f}" if req.run_cost is not None else "—"

        with st.expander(
            f"**{req.title}** — {req.score}/100 (Grade {grade})  •  {completed_str}"
        ):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Score", f"{req.score}/100")
            col2.metric("Grade", grade)
            col3.metric("Type", ft_label)
            col4.metric("Cost", cost_str)

            if req.generated_spec:
                st.markdown("---")
                st.markdown(req.generated_spec)
                st.download_button(
                    "⬇ Download Spec",
                    data=req.generated_spec,
                    file_name=f"spec_{req.id[:8]}.md",
                    mime="text/markdown",
                    key=f"dl_{req.id}",
                )
