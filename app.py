# app.py
import uuid
import streamlit as st
from agents.router import classify_feature
from evaluation.eval_db import init_db
from evaluation.token_tracker import TokenTracker
from evaluation.audit_trail import AuditTrail, ROUTE, DRAFT, GENERATE, REVIEW, IMPROVE, COST_CHECK
from evaluation.cost_guardrails import CostGuard, CostLimitExceeded
from evaluation.result_store import ResultStore
from agents.draft_answerer import draft_section_answers
from agents.generator import generate_feature_spec
from agents.reviewer import review_feature_spec, review_sections
from agents.improver import improve_spec, polish_spec
from prompts import capabilities, experiences, webpages

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="SAFe Feature Spec System",
    page_icon="📋",
    layout="wide"
)

# ── Module map ───────────────────────────────────────────────────────────────
PROMPT_MODULES = {
    "CAPABILITY": capabilities,
    "EXPERIENCE": experiences,
    "WEBPAGE": webpages,
}

TYPE_DESCRIPTIONS = {
    "CAPABILITY": "Backend tools, APIs, integrations, reusable engines",
    "EXPERIENCE": "UI components, interactive frontend features",
    "WEBPAGE": "New pages or updates to existing pages on servicenow.com",
}

# Keys match Reviewer output exactly — no Roman numeral prefixes
INPUT_PROMPTS = {
    "Feature Definition & Objective": (
        "Who owns this feature? Provide: feature owner name, PM name, "
        "tech lead, and key reviewers with their roles."
    ),
    "Content Strategy & Value Proposition": (
        "What are the quantitative targets? Provide: specific KPIs, "
        "target metrics (e.g. 'improve form completion by 20%'), and "
        "link to parent Epic or strategic initiative."
    ),
    "Copywriting, Messaging & Compliance": (
        "What is the tone and voice for this feature? Provide: brand voice "
        "guidelines, key messages, and whether legal or compliance review is required."
    ),
    "SEO, SEM, Analytics": (
        "What are your SEO and campaign tracking requirements? Provide: "
        "target keywords, UTM parameters, SEM dependencies, KPI dashboard "
        "location, and any GDPR/CCPA considerations."
    ),
    "Campaigns": (
        "What paid or email campaigns support this feature? Provide: "
        "landing page specs, campaign attribution model, email campaign "
        "dependencies, and how campaign outcomes will be measured."
    ),
    "Engineering, Publishing, QA & Content Model": (
        "Provide a content model table showing field types, data sources, "
        "validation rules, and system mappings (e.g. Marketo field names, "
        "AEM component names). Also add timeline milestones and QA owner."
    ),
    "Studio, Design & Accessibility": (
        "What are the performance targets and taxonomy requirements? Provide: "
        "load time SLA, Core Web Vitals targets, tagging structure, and "
        "any specific media or interactivity requirements."
    ),
    "Scope, Out of Scope, and Dependencies": (
        "What external dependencies need to be listed? Provide: system SLAs, "
        "API limits, platform availability, and any traceability "
        "links to the parent Epic."
    ),
}

# ── Session state init ───────────────────────────────────────────────────────
def init_state():
    defaults = {
        "stage": "input",
        "feature_type": None,
        "notes": "",
        "description": "",
        "section_answers": {},
        "spec": None,
        "scorecard": None,
        "improved_spec": None,
        "improved_scorecard": None,
        "additional_context": {},
        "run_id": None,
        "tracker": None,
        "guard": None,
        "trail": None,
        "_tracker_flushed": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_state()
init_db()

# ── Helper: reset to start ───────────────────────────────────────────────────
def reset():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


def init_pipeline_run():
    run_id = str(uuid.uuid4())
    st.session_state.run_id = run_id
    st.session_state.tracker = TokenTracker()
    st.session_state.trail = AuditTrail()
    st.session_state.guard = CostGuard()
    st.session_state._tracker_flushed = False
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


# ── Progress indicator ───────────────────────────────────────────────────────
STAGES = ["input", "draft", "generate", "review", "final"]
STAGE_LABELS = ["1. Input", "2. Interview", "3. Generate", "4. Review", "5. Final"]

def show_progress():
    stage = st.session_state.stage
    current = STAGES.index(stage) if stage in STAGES else 0
    cols = st.columns(len(STAGES))
    for i, (col, label) in enumerate(zip(cols, STAGE_LABELS)):
        if i < current:
            col.markdown(f"~~{label}~~ ✅")
        elif i == current:
            col.markdown(f"**{label}** ◀")
        else:
            col.markdown(f"{label}")
    st.divider()


# ════════════════════════════════════════════════════════════════════════════
# STAGE 1: INPUT
# ════════════════════════════════════════════════════════════════════════════
def stage_input():
    st.title("📋 SAFe Feature Spec System")
    st.caption("Replaces your 3-prompt, 2-session manual workflow.")
    show_progress()

    st.subheader("Describe your feature")
    description = st.text_area(
        "Feature description",
        placeholder=(
            "e.g. Build a progressive profiling form that captures user data "
            "over multiple visits..."
        ),
        height=100,
        label_visibility="collapsed"
    )

    st.subheader("Paste your notes")
    st.caption(
        "Meeting notes, Slack threads, strategy docs, requirements — anything "
        "you have. The more context, the better the draft answers."
    )
    notes = st.text_area(
        "Notes",
        placeholder="Paste any relevant notes, requirements, or context here...",
        height=250,
        label_visibility="collapsed"
    )

    if st.button("→ Start", type="primary", disabled=not description.strip()):
        init_pipeline_run()
        with st.spinner("Classifying feature type..."):
            feature_type = classify_feature(description, tracker=st.session_state.tracker)

        trail = st.session_state.trail
        run_id = st.session_state.run_id
        if trail and run_id:
            trail.log_event(run_id, ROUTE, {
                "input_description": description[:200],
                "classified_as": feature_type,
            })

        st.session_state.feature_type = feature_type
        st.session_state.notes = notes
        st.session_state.description = description
        st.session_state.stage = "draft"
        st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE 2: DRAFT (Interview + Draft Answerer)
# ════════════════════════════════════════════════════════════════════════════
def stage_draft():
    st.title("📋 SAFe Feature Spec System")
    show_progress()

    feature_type = st.session_state.feature_type
    module = PROMPT_MODULES[feature_type]

    # Feature type display + override
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader(f"Feature type: **{feature_type}**")
        st.caption(TYPE_DESCRIPTIONS[feature_type])
    with col2:
        override = st.selectbox(
            "Override type",
            options=["CAPABILITY", "EXPERIENCE", "WEBPAGE"],
            index=["CAPABILITY", "EXPERIENCE", "WEBPAGE"].index(feature_type),
            label_visibility="collapsed"
        )
        if override != feature_type:
            st.session_state.feature_type = override
            st.session_state.section_answers = {}
            st.rerun()

    st.divider()

    # Draft all sections if not already done
    if not st.session_state.section_answers:
        sections = list(module.SECTIONS.items())
        progress_bar = st.progress(0, text="Drafting answers from your notes...")
        for i, (section_name, questions) in enumerate(sections):
            progress_bar.progress(
                (i + 1) / len(sections),
                text=f"Drafting: {section_name}..."
            )
            st.session_state.section_answers[section_name] = draft_section_answers(
                notes=st.session_state.notes,
                feature_type=feature_type,
                section_name=section_name,
                questions=questions,
                tracker=st.session_state.tracker
            )
        progress_bar.empty()
        st.rerun()

    # Display editable sections
    st.subheader("Review and edit draft answers")
    st.caption(
        "The system drafted these from your notes. Edit any answer before "
        "generating the spec. Sections marked ⚠️ or 🚨 require your attention."
    )

    updated_answers = {}
    total_gaps = 0

    for section_name, draft_text in st.session_state.section_answers.items():
        needs_input_count = draft_text.count("[NEEDS INPUT:")
        total_questions = len(module.SECTIONS.get(section_name, []))
        gap_pct = round(needs_input_count / total_questions * 100) if total_questions > 0 else 0
        total_gaps += needs_input_count

        if gap_pct >= 50:
            label = (
                f"**{section_name}** 🚨 {needs_input_count}/{total_questions} "
                f"questions need your input"
            )
            expanded = True
        elif needs_input_count > 0:
            label = f"**{section_name}** ⚠️ {needs_input_count} gap(s)"
            expanded = True
        else:
            label = f"**{section_name}** ✅"
            expanded = False

        with st.expander(label, expanded=expanded):
            edited = st.text_area(
                section_name,
                value=draft_text,
                height=300,
                key=f"section_{section_name}",
                label_visibility="collapsed"
            )
            updated_answers[section_name] = edited

    st.divider()

    # Pre-generate gap analysis for high-value rubric sections
    HIGH_VALUE_SECTIONS = {
        "SEO & Analytics": 12,
        "Copywriting": 6,
        "Campaigns": 6,
        "Content Strategy & Purpose": 5,
        "Content Strategy": 5,
    }

    gap_warnings = []
    for section_name, points in HIGH_VALUE_SECTIONS.items():
        answers = updated_answers.get(section_name, "")
        gap_count = answers.count("[NEEDS INPUT:")
        if gap_count > 0:
            gap_warnings.append(
                f"**{section_name}** ({points} rubric points) — "
                f"{gap_count} gap(s) unfilled"
            )

    if gap_warnings:
        st.warning(
            "⚠️ These high-value sections have unfilled gaps. Filling them "
            "before generating will meaningfully improve your score:\n\n" +
            "\n".join(f"- {w}" for w in gap_warnings)
        )
    elif total_gaps == 0:
        st.success("✅ All sections complete — you're set up for a strong score.")
    else:
        st.info(
            f"ℹ️ {total_gaps} gap(s) remain in lower-weighted sections. "
            "You can fill them now or let the Improver infer from context."
        )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("→ Generate Spec", type="primary"):
            st.session_state.section_answers = updated_answers
            st.session_state.stage = "generate"
            st.rerun()
    with col2:
        if st.button("↺ Start Over"):
            reset()


# ════════════════════════════════════════════════════════════════════════════
# STAGE 3: GENERATE
# ════════════════════════════════════════════════════════════════════════════
def stage_generate():
    st.title("📋 SAFe Feature Spec System")
    show_progress()

    feature_type = st.session_state.feature_type
    module = PROMPT_MODULES[feature_type]

    guard = st.session_state.guard
    tracker = st.session_state.tracker
    if guard and tracker:
        guard.sync_from_tracker(tracker)
        try:
            guard.check_before_call("generator")
        except CostLimitExceeded as e:
            st.error(f"⚠️ Cost limit reached: {e}")
            st.info(f"Run cost so far: ${guard.run_cost:.4f}")
            st.stop()

    with st.spinner("Generating SAFe Feature spec..."):
        spec = generate_feature_spec(
            feature_type=feature_type,
            preamble=module.PREAMBLE,
            section_answers=st.session_state.section_answers,
            tracker=st.session_state.tracker
        )

    trail = st.session_state.trail
    run_id = st.session_state.run_id
    if trail and run_id:
        trail.log_event(run_id, GENERATE, {
            "feature_type": st.session_state.feature_type,
            "section_count": len(st.session_state.section_answers),
            "output_length_chars": len(spec),
        })

    st.session_state.spec = spec
    st.session_state.stage = "review"
    st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE 4: REVIEW
# ════════════════════════════════════════════════════════════════════════════
def stage_review():
    st.title("📋 SAFe Feature Spec System")
    show_progress()

    # Review if not already done
    if st.session_state.scorecard is None:
        guard = st.session_state.guard
        tracker = st.session_state.tracker
        if guard and tracker:
            guard.sync_from_tracker(tracker)
            try:
                guard.check_before_call("reviewer")
            except CostLimitExceeded as e:
                st.error(f"⚠️ Cost limit reached: {e}")
                st.info(f"Run cost so far: ${guard.run_cost:.4f}")
                st.stop()

        with st.spinner("Scoring spec against 100-point rubric..."):
            scorecard = review_feature_spec(
                st.session_state.spec,
                feature_type=st.session_state.feature_type,
                use_advisor=st.session_state.get("use_advisor", False),
                tracker=st.session_state.tracker
            )
        st.session_state.scorecard = scorecard

        trail = st.session_state.trail
        run_id = st.session_state.run_id
        if trail and run_id:
            weak = [name for name, data in scorecard.get("sections", {}).items()
                    if data["max_points"] > 0 and data["score"] / data["max_points"] < 0.75]
            trail.log_event(run_id, REVIEW, {
                "total_score": scorecard.get("total_score", 0),
                "max_score": 100,
                "weak_sections": weak,
                "passed": scorecard.get("total_score", 0) >= 90,
            })

    scorecard = st.session_state.scorecard

    if "parse_error" in scorecard:
        st.error(f"Reviewer error: {scorecard['parse_error']}")
        st.code(scorecard.get("raw_response", "")[:1000])
        return

    # Score display
    total = scorecard["total_score"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Score", f"{total}/100")
    col2.metric(
        "Grade",
        "A" if total >= 90 else "B" if total >= 80 else "C" if total >= 70 else "D"
    )
    col3.metric(
        "Leadership Review",
        "✅ Ready" if total >= 90 else "⚠️ Not Yet"
    )

    st.divider()

    # Section breakdown
    st.subheader("Section Scores")
    for section_name, section_data in scorecard["sections"].items():
        score = section_data["score"]
        max_pts = section_data["max_points"]
        pct = round(score / max_pts * 100) if max_pts > 0 else 0
        flag = "⚠️" if pct < 75 else "✅"
        rec = section_data.get("recommendations", "")

        with st.expander(f"{flag} {section_name}: {score}/{max_pts} ({pct}%)"):
            if rec:
                st.caption(f"**Recommendations:** {rec}")
            else:
                st.caption("No recommendations — this section scored well.")

    st.divider()

    # View the spec
    with st.expander("📄 View Generated Spec", expanded=False):
        st.markdown(st.session_state.spec)
        st.download_button(
            "⬇ Download Spec",
            data=st.session_state.spec,
            file_name="safe_feature_spec.md",
            mime="text/markdown"
        )

    # Identify weak sections
    weak_sections_data = {
        name: data
        for name, data in scorecard["sections"].items()
        if data["max_points"] > 0
        and data["score"] / data["max_points"] < 0.75
    }
    weak_count = len(weak_sections_data)

    # Boost inputs — collect PM context before improving
    if weak_count > 0:
        st.subheader("💡 Boost your score before improving")
        st.caption(
            "The Improver will infer what it can from your spec, but these "
            "sections need information only you can provide. Fill in any fields "
            "where you have the details — each one helps. Leave blank to let "
            "the Improver infer from context."
        )

        for section_name in weak_sections_data:
            if section_name in INPUT_PROMPTS:
                score = weak_sections_data[section_name]["score"]
                max_pts = weak_sections_data[section_name]["max_points"]
                pct = round(score / max_pts * 100)

                current_value = st.session_state.additional_context.get(
                    section_name, ""
                )

                user_input = st.text_area(
                    f"{section_name} — {score}/{max_pts} ({pct}%)",
                    value=current_value,
                    placeholder=INPUT_PROMPTS[section_name],
                    height=100,
                    key=f"boost_{section_name}"
                )

                if user_input and user_input.strip():
                    st.session_state.additional_context[section_name] = user_input
                elif section_name in st.session_state.additional_context:
                    del st.session_state.additional_context[section_name]

        st.divider()

    # Action buttons
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        if weak_count > 0:
            if st.button(
                f"⚡ Improve {weak_count} Weak Section(s)",
                type="primary"
            ):
                st.session_state.stage = "improve"
                st.rerun()
        else:
            st.success("✅ All sections above 75% — no improvement needed.")
            if st.button("→ Finish", type="primary"):
                st.session_state.improved_spec = st.session_state.spec
                st.session_state.improved_scorecard = scorecard
                st.session_state.stage = "final"
                st.rerun()
    with col2:
        if st.button("→ Accept & Finish", type="secondary"):
            st.session_state.improved_spec = st.session_state.spec
            st.session_state.improved_scorecard = scorecard
            st.session_state.stage = "final"
            st.rerun()
    with col3:
        if st.button("↺ Start Over"):
            reset()


# ── Helper: merge scorecards after section-isolated re-scoring ───────────
def _merge_scorecards(
    base_scorecard: dict,
    partial_scorecard: dict,
    changed_sections: set[str]
) -> dict:
    """
    Merge a partial re-scoring into a full scorecard.

    Sections in changed_sections get their scores from partial_scorecard,
    subject to two guards:
    - Floor clamp: a re-scored section can never score LOWER than its base score.
      This prevents Reviewer inconsistency from turning improvements into regressions.
    - Ceiling clamp: a re-scored section can never exceed its max_points.
      This prevents the Reviewer from awarding bonus points beyond the rubric max.

    All other sections carry forward their scores from base_scorecard.
    total_score is recomputed from the merged section scores.
    """
    merged = {
        "sections": {}
    }

    for name, data in base_scorecard.get("sections", {}).items():
        if name in changed_sections and name in partial_scorecard.get("sections", {}):
            new_data = partial_scorecard["sections"][name]
            base_score = data.get("score", 0)
            new_score = new_data.get("score", 0)
            max_pts = data.get("max_points", new_data.get("max_points", 100))

            # Floor clamp: never regress below base score
            # Ceiling clamp: never exceed max points
            clamped_score = max(new_score, base_score)
            clamped_score = min(clamped_score, max_pts)

            new_data = dict(new_data)  # shallow copy to avoid mutating original
            new_data["score"] = clamped_score
            merged["sections"][name] = new_data
        else:
            # Carry forward original score
            merged["sections"][name] = data

    # Recompute total from merged section scores
    merged["total_score"] = sum(
        section_data.get("score", 0)
        for section_data in merged["sections"].values()
    )

    return merged


# ════════════════════════════════════════════════════════════════════════════
# STAGE 4b: IMPROVE
# ════════════════════════════════════════════════════════════════════════════
def stage_improve():
    st.title("📋 SAFe Feature Spec System")
    show_progress()

    additional_context = st.session_state.get("additional_context", {})
    original_scorecard = st.session_state.scorecard

    # Record which sections were originally weak (below 75%)
    originally_weak = {
        name for name, data in original_scorecard.get("sections", {}).items()
        if data["max_points"] > 0
        and data["score"] / data["max_points"] < 0.75
    }

    trail = st.session_state.trail
    run_id = st.session_state.run_id
    guard = st.session_state.guard
    tracker = st.session_state.tracker

    # ── Pass 1: improve all originally-weak sections ─────────────────────
    if guard and tracker:
        guard.sync_from_tracker(tracker)
        try:
            guard.check_before_call("improver")
        except CostLimitExceeded as e:
            st.error(f"⚠️ Cost limit reached: {e}")
            st.info(f"Run cost so far: ${guard.run_cost:.4f}")
            st.stop()

    with st.spinner("Improving weak sections (pass 1 of 2)..."):
        improved = improve_spec(
            st.session_state.spec,
            original_scorecard,
            additional_context,
            use_advisor=st.session_state.get("use_advisor", False),
            tracker=st.session_state.tracker
        )

    # Determine which sections were actually changed by the Improver
    changed_sections = set(improve_spec.last_debug.get("weak_rubric_sections", []))

    # ── Section-isolated re-scoring ──────────────────────────────────────
    # Only re-score sections the Improver actually changed.
    # Untouched sections carry forward their original scores.
    # This prevents the Reviewer from drifting scores on sections
    # whose text hasn't changed.
    with st.spinner("Re-scoring improved sections..."):
        if changed_sections:
            partial_scorecard = review_sections(
                improved, list(changed_sections),
                feature_type=st.session_state.feature_type,
                use_advisor=st.session_state.get("use_advisor", False),
                tracker=st.session_state.tracker
            )
        else:
            partial_scorecard = {"sections": {}}

    # Merge: original scores for untouched sections, fresh scores for changed ones
    improved_scorecard = _merge_scorecards(
        original_scorecard, partial_scorecard, changed_sections
    )

    if trail and run_id:
        trail.log_event(run_id, IMPROVE, {
            "iteration": 1,
            "sections_targeted": list(changed_sections),
            "score_before": original_scorecard.get("total_score", 0),
            "score_after": improved_scorecard.get("total_score", 0),
        })

    # ── Pass 2: strictly guarded ─────────────────────────────────────────
    if "parse_error" not in improved_scorecard:
        first_score = improved_scorecard.get("total_score", 0)
        original_score = original_scorecard.get("total_score", 0)
        made_progress = first_score > original_score

        still_weak_and_originally_weak = [
            name for name, data in improved_scorecard["sections"].items()
            if name in originally_weak
            and data["max_points"] > 0
            and data["score"] / data["max_points"] < 0.75
        ]

        # Regression check: any originally-strong section now failing?
        # (Should not happen with section-isolated scoring, but kept as safety net)
        regressions = [
            name for name, data in improved_scorecard["sections"].items()
            if name not in originally_weak
            and data["max_points"] > 0
            and data["score"] / data["max_points"] < 0.75
        ]

        if not regressions and still_weak_and_originally_weak and made_progress:
            filtered_scorecard = {
                "total_score": improved_scorecard.get("total_score", 0),
                "sections": {
                    name: data
                    for name, data in improved_scorecard["sections"].items()
                    if name in originally_weak
                }
            }

            if guard and tracker:
                guard.sync_from_tracker(tracker)
                try:
                    guard.check_before_call("improver")
                except CostLimitExceeded as e:
                    st.error(f"⚠️ Cost limit reached: {e}")
                    st.info(f"Run cost so far: ${guard.run_cost:.4f}")
                    st.stop()

            with st.spinner(
                f"Running second pass on {len(still_weak_and_originally_weak)} "
                f"remaining weak section(s)..."
            ):
                improved = improve_spec(
                    improved,
                    filtered_scorecard,
                    additional_context,
                    use_advisor=st.session_state.get("use_advisor", False),
                    tracker=st.session_state.tracker
                )

            changed_pass2 = set(improve_spec.last_debug.get("weak_rubric_sections", []))

            with st.spinner("Re-scoring after second pass..."):
                if changed_pass2:
                    partial_scorecard_2 = review_sections(
                        improved, list(changed_pass2),
                        feature_type=st.session_state.feature_type,
                        use_advisor=st.session_state.get("use_advisor", False),
                        tracker=st.session_state.tracker
                    )
                else:
                    partial_scorecard_2 = {"sections": {}}

            improved_scorecard = _merge_scorecards(
                improved_scorecard, partial_scorecard_2, changed_pass2
            )

            if trail and run_id:
                trail.log_event(run_id, IMPROVE, {
                    "iteration": 2,
                    "sections_targeted": list(changed_pass2),
                    "score_before": first_score,
                    "score_after": improved_scorecard.get("total_score", 0),
                })

    # ── Tier 2: Polish pass (auto-trigger if score is 80-89) ────────────────
    # Sections scoring 75-89% get light-touch append-only edits.
    # Skipped if already at 90+ or if Tier 1 didn't reach 80.
    tier2_total = improved_scorecard.get("total_score", 0)
    if 80 <= tier2_total < 90 and "parse_error" not in improved_scorecard:
        with st.spinner("Polishing sections to reach 90..."):
            polished = polish_spec(
                improved,
                improved_scorecard,
                additional_context,
                use_advisor=st.session_state.get("use_advisor", False),
                tracker=st.session_state.tracker
            )

        polish_changed = set(polish_spec.last_debug.get("polish_candidates", []))

        if polish_changed:
            with st.spinner("Re-scoring polished sections..."):
                partial_polish = review_sections(
                    polished, list(polish_changed),
                    feature_type=st.session_state.feature_type,
                    use_advisor=st.session_state.get("use_advisor", False),
                    tracker=st.session_state.tracker
                )

            improved_scorecard = _merge_scorecards(
                improved_scorecard, partial_polish, polish_changed
            )
            improved = polished

    st.session_state.improved_spec = improved
    st.session_state.improved_scorecard = improved_scorecard
    st.session_state.stage = "final"
    st.rerun()


# ════════════════════════════════════════════════════════════════════════════
# STAGE 5: FINAL
# ════════════════════════════════════════════════════════════════════════════
def stage_final():
    st.title("📋 SAFe Feature Spec System")
    show_progress()

    original_score = st.session_state.scorecard.get("total_score", 0)
    improved_scorecard = st.session_state.improved_scorecard
    final_spec = st.session_state.improved_spec

    # Score comparison
    if improved_scorecard and "parse_error" not in improved_scorecard:
        improved_score = improved_scorecard["total_score"]
        delta = improved_score - original_score

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Original Score", f"{original_score}/100")
        col2.metric(
            "Final Score",
            f"{improved_score}/100",
            delta=delta,
            delta_color="normal"
        )
        col3.metric(
            "Grade",
            "A" if improved_score >= 90
            else "B" if improved_score >= 80
            else "C" if improved_score >= 70
            else "D"
        )
        col4.metric(
            "Leadership Review",
            "✅ Ready" if improved_score >= 90 else "⚠️ Not Yet"
        )

        # Section before/after comparison
        with st.expander("📊 Section-by-section comparison", expanded=False):
            for section_name in st.session_state.scorecard["sections"]:
                if section_name not in improved_scorecard["sections"]:
                    continue
                before = st.session_state.scorecard["sections"][section_name]["score"]
                after = improved_scorecard["sections"][section_name]["score"]
                max_pts = st.session_state.scorecard["sections"][section_name]["max_points"]
                before_pct = round(before / max_pts * 100)
                after_pct = round(after / max_pts * 100)
                arrow = "↑" if after > before else ("↓" if after < before else "→")
                flag = "⚠️" if after_pct < 75 else "✅"
                st.markdown(
                    f"{arrow} {flag} **{section_name}**: "
                    f"{before}/{max_pts} ({before_pct}%) → "
                    f"{after}/{max_pts} ({after_pct}%)"
                )
    else:
        st.metric("Score", f"{original_score}/100")

    st.divider()
    st.subheader("Your SAFe Feature Spec")
    st.markdown(final_spec)

    st.divider()

    tracker = st.session_state.get("tracker")
    trail = st.session_state.get("trail")
    run_id = st.session_state.get("run_id")

    with st.expander("🔍 Run Details", expanded=False):
        if tracker:
            summary = tracker.summary()
            st.metric("API Cost", f"${summary['cost_usd']:.4f}")
            st.caption(
                f"Total tokens: {summary['input']:,} in / {summary['output']:,} out "
                f"across {summary['calls']} calls"
            )
            for agent, data in summary.get("by_agent", {}).items():
                st.caption(
                    f"  {agent}: {data['input']:,} in / {data['output']:,} out "
                    f"({data['calls']} calls)"
                )

        if trail and run_id:
            events = trail.get_trace(run_id)
            if events:
                st.caption(f"Audit trail: {len(events)} events")
                for ev in events:
                    st.caption(f"  {ev['timestamp']} — {ev['event_type']}")

    if tracker and run_id and not st.session_state.get("_tracker_flushed"):
        tracker.flush_to_db(run_id)
        st.session_state._tracker_flushed = True

    if run_id:
        store = ResultStore()
        if improved_scorecard and "parse_error" not in improved_scorecard:
            final_score_val = improved_scorecard.get("total_score", 0)
            final_scorecard = improved_scorecard
        else:
            final_score_val = original_score
            final_scorecard = st.session_state.scorecard or {}
        store.update_run(
            run_id,
            feature_type=st.session_state.feature_type or "UNKNOWN",
            scorecard=final_scorecard,
            original_score=original_score,
            final_score=final_score_val,
            passed=final_score_val >= 90,
        )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "⬇ Download Spec (.md)",
            data=final_spec,
            file_name="safe_feature_spec.md",
            mime="text/markdown",
            type="primary"
        )
    with col2:
        if st.button("↺ Build Another Spec"):
            reset()


# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
use_advisor = st.sidebar.checkbox("🧠 Use Opus Advisor (Reviewer + Improver)", value=False)
st.session_state["use_advisor"] = use_advisor

# ════════════════════════════════════════════════════════════════════════════
# STAGE ROUTER
# ════════════════════════════════════════════════════════════════════════════
stage = st.session_state.stage

if stage == "input":
    stage_input()
elif stage == "draft":
    stage_draft()
elif stage == "generate":
    stage_generate()
elif stage == "review":
    stage_review()
elif stage == "improve":
    stage_improve()
elif stage == "final":
    stage_final()