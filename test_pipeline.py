# test_pipeline.py
import sys
import os
sys.path.insert(0, '.')

from agents.draft_answerer import draft_section_answers
from agents.generator import generate_feature_spec
from agents.reviewer import review_feature_spec
from prompts import capabilities

SAMPLE_NOTES = """
Meeting notes from 2/14 kickoff — Progressive Profiling Form

Goal: Capture additional user data over multiple visits rather than asking
for everything upfront. Reduces form abandonment, improves lead quality.

Target users: Net-new visitors and returning known users on servicenow.com.
Known users should see a shorter form (fields we already have pre-filled or hidden).
Net-new visitors get the standard form.

Tech stack confirmed:
- Adobe Target for A/B test delivery and audience targeting
- Tealium CDP for event forwarding and identity resolution
- Marketo as the MAP for lead capture downstream
- Arc Design System for all UI components (no custom styling)
- AEM as the CMS — form config managed there, not hardcoded

Reusability: This should be a reusable capability. Multiple teams want to
use progressive profiling — events pages, product pages, resource downloads.
Build it once, deploy anywhere.

WCAG 2.2 compliance required. Gryffindors team owns QA and implementation.
Target launch: Q2 PI (PI 26.2). No hard content freeze identified yet.

Open questions:
- How many fields max per visit? Suggestion: 2-3 new fields per session
- Do we need a fallback if Tealium is unavailable? Probably yes — default to full form
- Legal review needed for data capture fields (privacy team to confirm)
"""

FEATURE_TYPE = "CAPABILITY"

# ── Step 1: Draft answers for all sections ──────────────────────────────────
print("Step 1: Drafting answers for all sections...")
section_answers = {}
for section_name, questions in capabilities.SECTIONS.items():
    print(f"  Drafting: {section_name} ({len(questions)} questions)")
    section_answers[section_name] = draft_section_answers(
        notes=SAMPLE_NOTES,
        feature_type=FEATURE_TYPE,
        section_name=section_name,
        questions=questions
    )
print(f"  Done. {len(section_answers)} sections drafted.\n")

# ── Step 2: Generate the spec ────────────────────────────────────────────────
print("Step 2: Generating SAFe Feature spec...")
spec = generate_feature_spec(
    feature_type=FEATURE_TYPE,
    preamble=capabilities.PREAMBLE,
    section_answers=section_answers
)
print(f"  Done. Spec is {len(spec)} characters.\n")

# Print the spec
print("=" * 60)
print("GENERATED SPEC:")
print("=" * 60)
print(spec)
print("=" * 60)

# ── Step 3: Review the spec ──────────────────────────────────────────────────
print("\nStep 3: Reviewing spec against 100-point rubric...")
scorecard = review_feature_spec(spec)

if "parse_error" in scorecard:
    print(f"  ERROR parsing reviewer response: {scorecard['parse_error']}")
    print(f"  Raw response: {scorecard['raw_response'][:500]}")
else:
    print(f"\n{'=' * 60}")
    print(f"SCORECARD: {scorecard['total_score']}/100")
    print(f"{'=' * 60}")

    for section_name, section_data in scorecard["sections"].items():
        score = section_data["score"]
        max_pts = section_data["max_points"]
        pct = round(score / max_pts * 100) if max_pts > 0 else 0
        flag = " ⚠️" if pct < 75 else " ✅"
        print(f"{flag} {section_name}: {score}/{max_pts} ({pct}%)")
        if section_data.get("recommendations"):
            print(f"     → {section_data['recommendations'][:120]}")

    # Identify weak sections for the Improver
    weak = [
        name for name, data in scorecard["sections"].items()
        if data["score"] / data["max_points"] < 0.75
    ]
    print(f"\nSections below 75%: {len(weak)}")
    for s in weak:
        print(f"  - {s}")

# ── Step 4: Improve the spec ─────────────────────────────────────────────────
from agents.improver import improve_spec

print("\nStep 4: Improving weak sections...")
improved_spec = improve_spec(spec, scorecard)

if improved_spec == spec:
    print("  No sections below 75% — nothing to improve.")
else:
    print(f"  Done. Improved spec is {len(improved_spec)} characters.\n")

    # Step 5: Re-review the improved spec
    print("Step 5: Re-reviewing improved spec...")
    improved_scorecard = review_feature_spec(improved_spec)

    if "parse_error" in improved_scorecard:
        print(f"  ERROR: {improved_scorecard['parse_error']}")
    else:
        print(f"\n{'=' * 60}")
        print(f"BEFORE vs AFTER:")
        print(f"{'=' * 60}")
        print(f"Original score:  {scorecard['total_score']}/100")
        print(f"Improved score:  {improved_scorecard['total_score']}/100")
        delta = improved_scorecard['total_score'] - scorecard['total_score']
        print(f"Delta:           +{delta} points\n")

        for section_name in scorecard["sections"]:
            if section_name not in improved_scorecard["sections"]:
                continue
            before = scorecard["sections"][section_name]["score"]
            after = improved_scorecard["sections"][section_name]["score"]
            max_pts = scorecard["sections"][section_name]["max_points"]
            before_pct = round(before / max_pts * 100)
            after_pct = round(after / max_pts * 100)
            changed = "↑" if after > before else ("↓" if after < before else "→")
            flag = " ⚠️" if after_pct < 75 else " ✅"
            print(
                f"{changed}{flag} {section_name}: "
                f"{before}/{max_pts} ({before_pct}%) → "
                f"{after}/{max_pts} ({after_pct}%)"
            )