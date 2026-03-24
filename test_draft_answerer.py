# test_draft_answerer.py
import sys
import os
sys.path.insert(0, '.')

from agents.draft_answerer import draft_section_answers
from prompts import capabilities

# Sample notes — realistic PM working notes for a Capability feature
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

# Test one section at a time — start with Strategy & Purpose
section_name = "Strategy & Purpose"
questions = capabilities.SECTIONS[section_name]

print(f"=== DRAFT ANSWERER TEST ===")
print(f"Feature type: CAPABILITY")
print(f"Section: {section_name}")
print(f"Questions: {len(questions)}")
print("=" * 50)
print()

result = draft_section_answers(
    notes=SAMPLE_NOTES,
    feature_type="CAPABILITY",
    section_name=section_name,
    questions=questions
)

print(result)
print()
print("=" * 50)

# Count how many answers needed input vs. were drafted from notes
needs_input_count = result.count("[NEEDS INPUT:")
drafted_count = len(questions) - needs_input_count
print(f"\nSummary: {drafted_count}/{len(questions)} answered from notes, "
      f"{needs_input_count}/{len(questions)} flagged for PM input")

# Add to test_draft_answerer.py — test the NEEDS INPUT flag
print("\n=== TESTING NEEDS INPUT FLAG ===")
print("Section: Testing & QA (notes have minimal QA info)\n")

result2 = draft_section_answers(
    notes=SAMPLE_NOTES,
    feature_type="CAPABILITY",
    section_name="Testing & QA",
    questions=capabilities.SECTIONS["Testing & QA"]
)
print(result2)

needs_input_count = result2.count("[NEEDS INPUT:")
print(f"\nNeeds input flags: {needs_input_count}/{len(capabilities.SECTIONS['Testing & QA'])}")