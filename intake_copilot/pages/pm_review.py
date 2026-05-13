"""
PM Review — page logic.

Call render() to draw the page. set_page_config must be called by the host
script before render() if running inside a multi-page app.

Can also be run as a standalone Streamlit page:
    streamlit run intake_copilot/pages/pm_review.py
"""

import streamlit as st

from intake_copilot.agent import IntakeCopilot
from intake_copilot.models import IntakeRecord
from intake_copilot.pm_review import PMReviewRecord
from intake_copilot.pipeline_bridge import run_pipeline_from_intake


def render() -> None:
    st.title("PM Review")

    # ── Guard: must have a completed copilot session ──────────────────────────
    copilot: IntakeCopilot | None = st.session_state.get("copilot")

    if copilot is None or copilot._manager.state.value != "confirmed":
        st.warning(
            "No completed intake session found. "
            "Complete a stakeholder intake first."
        )
        if st.button("Go to Stakeholder Intake"):
            # Works when served from the main app (pages/stakeholder_intake.py)
            # and from intake_app.py (st.navigation handles routing).
            try:
                st.switch_page("pages/stakeholder_intake.py")
            except Exception:
                st.info("Navigate to 'Stakeholder Intake' in the sidebar.")
        st.stop()

    # ── Build or retrieve PMReviewRecord ──────────────────────────────────────
    if "pm_review_record" not in st.session_state:
        record: IntakeRecord = copilot.get_intake_record()
        recommendation = copilot.get_advisor_recommendation()
        st.session_state["pm_review_record"] = PMReviewRecord(
            intake_record=record,
            recommendation=recommendation,
            conversation_transcript=copilot._record.conversation_history,
            stakeholder_raw_input=copilot._record.stakeholder_input_raw,
            pm_field_edits={},
        )

    pm: PMReviewRecord = st.session_state["pm_review_record"]
    record = pm.intake_record

    # ── Header ────────────────────────────────────────────────────────────────
    feature_name = record.feature_name.value or "Untitled Feature"
    action = pm.recommendation.get("action", "")

    _badge_color = {
        "accept": "green",
        "accept_with_caveats": "orange",
        "needs_more_input": "red",
    }.get(action, "grey")

    _badge_label = {
        "accept": "Ready",
        "accept_with_caveats": "Ready with caveats",
        "needs_more_input": "Needs more input",
    }.get(action, action)

    st.subheader(feature_name)
    st.markdown(f"**Copilot recommendation:** :{_badge_color}[{_badge_label}]")
    st.divider()

    # ── Section 1: Intake Summary ─────────────────────────────────────────────
    st.header("1. Intake Summary")

    _TIER_LABELS = {"core": "Core", "context": "Context", "detail": "Detail"}
    _STATUS_ICONS = {
        "populated": "✓",
        "unknown": "?",
        "unasked": "—",
    }

    _ALL_FIELDS = [
        ("feature_name", "Feature Name"),
        ("feature_type", "Feature Type"),
        ("problem_statement", "Problem Statement"),
        ("business_objective", "Business Objective"),
        ("target_audience", "Target Audience"),
        ("success_metrics", "Success Metrics"),
        ("dependencies", "Dependencies"),
        ("timeline_constraints", "Timeline Constraints"),
        ("solution_approach", "Solution Approach"),
        ("scope_inclusions", "Scope Inclusions"),
        ("scope_exclusions", "Scope Exclusions"),
        ("additional_context", "Additional Context"),
    ]

    edits: dict = pm.pm_field_edits or {}

    for field_name, label in _ALL_FIELDS:
        f = getattr(record, field_name)
        icon = _STATUS_ICONS.get(f.status.value, "—")
        tier = _TIER_LABELS.get(f.tier, f.tier)
        current_val = edits.get(field_name, f.value or "")
        missing = not f.is_populated() and field_name not in edits

        col1, col2 = st.columns([1, 4])
        with col1:
            st.markdown(f"**{label}**")
            st.caption(f"{tier} · {icon}")
            if missing:
                st.caption(":red[missing]")

        with col2:
            edit_key = f"edit_toggle_{field_name}"

            if edit_key not in st.session_state:
                st.session_state[edit_key] = False

            if st.session_state[edit_key]:
                new_val = st.text_area(
                    label=f"Edit {label}",
                    value=current_val,
                    key=f"edit_area_{field_name}",
                    label_visibility="collapsed",
                    height=80,
                )
                col_save, col_cancel = st.columns([1, 5])
                with col_save:
                    if st.button("Save", key=f"save_{field_name}"):
                        pm.edit_field(field_name, new_val)
                        st.session_state["pm_review_record"] = pm
                        st.session_state[edit_key] = False
                        st.rerun()
                with col_cancel:
                    if st.button("Cancel", key=f"cancel_{field_name}"):
                        st.session_state[edit_key] = False
                        st.rerun()
            else:
                display = edits.get(field_name, f.value or "_not captured_")
                st.markdown(display)
                if st.button("Edit", key=f"edit_btn_{field_name}"):
                    st.session_state[edit_key] = True
                    st.rerun()

        st.divider()

    # ── Section 2: Feature Type ───────────────────────────────────────────────
    st.header("2. Feature Type")

    copilot_type = record.feature_type.value or ""
    confidence = record.feature_type_confidence
    options = ["CAPABILITY", "EXPERIENCE", "WEBPAGE"]
    default_idx = options.index(copilot_type.upper()) if copilot_type.upper() in options else 0
    confirmed_idx = options.index(pm.pm_feature_type) if pm.pm_feature_type else default_idx

    st.caption(
        f"Copilot suggestion: **{copilot_type or 'none'}** "
        f"(confidence: {confidence:.0%})"
    )

    selected_type = st.radio(
        "Confirm feature type",
        options=options,
        index=confirmed_idx,
        horizontal=True,
    )

    if st.button("Confirm Feature Type"):
        pm.set_feature_type(selected_type)
        st.session_state["pm_review_record"] = pm
        st.success(f"Feature type confirmed: {selected_type}")

    if pm.pm_feature_type:
        st.markdown(f":green[Confirmed:] **{pm.pm_feature_type}**")
    else:
        st.caption(":orange[Not yet confirmed — required before accepting.]")

    st.divider()

    # ── Section 3: Copilot Recommendation ────────────────────────────────────
    st.header("3. Copilot Recommendation")

    st.markdown(f"**Action:** {_badge_label}")
    st.markdown(f"**Rationale:** {pm.recommendation.get('rationale', '')}")

    gaps = pm.recommendation.get("gaps", [])
    if gaps:
        st.markdown("**Gaps:**")
        for g in gaps:
            st.markdown(f"- {g}")

    kb = pm.recommendation.get("knowledge_boundary", [])
    if kb:
        st.markdown("**Stakeholder said 'I don't know':**")
        for k in kb:
            st.markdown(f"- {k}")

    advisor_input = pm.recommendation.get("advisor_input")
    if advisor_input:
        with st.expander("Advisor analysis (Opus)"):
            st.markdown(advisor_input)

    st.divider()

    # ── Section 4: Boost Inputs ───────────────────────────────────────────────
    st.header("4. Boost Inputs")
    st.caption("Add context to guide the Reviewer stage. Optional.")

    boost_text = st.text_area(
        "Boost inputs",
        value=pm.pm_boost_inputs or "",
        height=120,
        label_visibility="collapsed",
        placeholder="Add any additional PM context, constraints, or guidance for the Generator…",
    )

    if st.button("Save Boost Inputs"):
        pm.add_boost_inputs(boost_text)
        st.session_state["pm_review_record"] = pm
        st.success("Boost inputs saved.")

    st.divider()

    # ── Section 5: Conversation Transcript ───────────────────────────────────
    st.header("5. Conversation Transcript")

    with st.expander("View full conversation"):
        for msg in pm.conversation_transcript:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            prefix = "**Stakeholder:**" if role == "user" else "**Copilot:**"
            st.markdown(f"{prefix} {content}")
            st.markdown("---")

    st.divider()

    # ── Actions ───────────────────────────────────────────────────────────────
    st.header("Actions")

    accept_disabled = pm.pm_feature_type is None
    col_accept, col_reject = st.columns(2)

    with col_accept:
        if st.button(
            "Accept & Send to Generator",
            type="primary",
            disabled=accept_disabled,
            help="Confirm feature type above before accepting." if accept_disabled else "",
        ):
            try:
                pm.accept()
                st.session_state["pm_review_record"] = pm
                st.session_state["generator_input"] = pm.to_generator_input()
                st.session_state["pipeline_result"] = None
            except Exception as e:
                st.error(str(e))

    with col_reject:
        with st.expander("Reject this intake"):
            rejection_reason = st.text_area(
                "Reason for rejection",
                placeholder="Explain why this intake is being rejected…",
            )
            if st.button("Confirm Rejection", type="secondary"):
                if rejection_reason.strip():
                    pm.reject(rejection_reason)
                    st.session_state["pm_review_record"] = pm
                    st.warning("Intake rejected.")
                else:
                    st.error("Please provide a rejection reason.")

    # ── Generator Input Preview + Pipeline Trigger ────────────────────────────
    gen_input: dict | None = st.session_state.get("generator_input")

    if gen_input is not None and pm.pm_decision == "accept":
        st.divider()
        st.subheader("Generator Input")

        st.markdown(f"**Feature Type:** {gen_input['feature_type']}")

        with st.expander("Feature description (synthesised)"):
            st.markdown(gen_input["feature_description"])

        if gen_input.get("boost_inputs"):
            with st.expander("Boost inputs"):
                st.markdown(gen_input["boost_inputs"])

        with st.expander("Section answers"):
            for section, content in gen_input["section_answers"].items():
                st.markdown(f"**{section}**")
                st.markdown(content)
                st.markdown("---")

        use_advisor = st.checkbox("Use Opus advisor (Reviewer + Improver)", value=False)

        if st.button("Run Pipeline", type="primary"):
            with st.spinner("Running Generator → Reviewer → Improver…"):
                result = run_pipeline_from_intake(gen_input, use_advisor=use_advisor)
            st.session_state["pipeline_result"] = result
            st.rerun()

    # ── Pipeline Result ───────────────────────────────────────────────────────
    pipeline_result = st.session_state.get("pipeline_result")
    if pipeline_result:
        st.divider()
        if pipeline_result.get("error"):
            st.error(
                f"Pipeline failed at **{pipeline_result['stage']}**: "
                f"{pipeline_result['message']}"
            )
        else:
            orig = pipeline_result["original_score"]
            final = pipeline_result["final_score"]
            delta = final - orig

            st.subheader("Pipeline Complete")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Original Score", f"{orig}/100")
            c2.metric("Final Score", f"{final}/100", delta=delta)
            c3.metric(
                "Grade",
                "A" if final >= 90 else "B" if final >= 80 else "C" if final >= 70 else "D",
            )
            c4.metric("Ready?", "✅ Yes" if final >= 90 else "⚠️ Not yet")

            st.divider()
            st.subheader("Generated SAFe Feature Spec")
            st.markdown(pipeline_result["spec"])

            st.download_button(
                "Download Spec (.md)",
                data=pipeline_result["spec"],
                file_name="safe_feature_spec.md",
                mime="text/markdown",
                type="primary",
            )

            with st.expander("Section scores"):
                for name, data in pipeline_result["scorecard"].get("sections", {}).items():
                    score = data.get("score", 0)
                    max_pts = data.get("max_points", 0)
                    pct = round(score / max_pts * 100) if max_pts else 0
                    flag = "✅" if pct >= 75 else "⚠️"
                    with st.expander(
                        f"{flag} {name}: {score}/{max_pts} ({pct}%)", expanded=pct < 75
                    ):
                        rec = data.get("recommendations", "")
                        if rec:
                            st.caption(rec)

            with st.expander("Run details"):
                summary = pipeline_result.get("token_summary", {})
                st.caption(f"Run ID: {pipeline_result['run_id']}")
                st.caption(f"API cost: ${pipeline_result.get('cost_usd', 0):.4f}")
                st.caption(
                    f"Tokens: {summary.get('input', 0):,} in / "
                    f"{summary.get('output', 0):,} out "
                    f"across {summary.get('calls', 0)} calls"
                )


# Allow running as a standalone Streamlit page:
#   streamlit run intake_copilot/pages/pm_review.py
if __name__ == "__main__":
    st.set_page_config(page_title="PM Review", layout="wide")
    render()
