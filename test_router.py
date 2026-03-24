# test_router.py
import sys
import os
sys.path.insert(0, '.')

# Export your API key if not already set
# os.environ["ANTHROPIC_API_KEY"] = "sk-ant-..."

from agents.router import classify_feature

test_cases = [
    # --- Clear CAPABILITY cases ---
    ("Build a progressive profiling engine that tracks user data across sessions",
     "CAPABILITY"),
    ("Create an Adobe Target integration for A/B test delivery on servicenow.com",
     "CAPABILITY"),
    ("Add a CDP event-forwarding pipeline from the website to Tealium",
     "CAPABILITY"),
    ("Build a buying group classification API that scores web visitors by role",
     "CAPABILITY"),
    ("Create a reusable personalization token library for email and web",
     "CAPABILITY"),

    # --- Clear EXPERIENCE cases ---
    ("Build a filter component for the events listing page",
     "EXPERIENCE"),
    ("Create an interactive product configurator with dynamic pricing display",
     "EXPERIENCE"),
    ("Add a sticky navigation bar with scroll-aware show/hide behavior",
     "EXPERIENCE"),
    ("Build a tabbed content module with animated state transitions",
     "EXPERIENCE"),
    ("Create a form component with progressive disclosure logic and validation states",
     "EXPERIENCE"),

    # --- Clear WEBPAGE cases ---
    ("Create a new ITSM product landing page on servicenow.com",
     "WEBPAGE"),
    ("Build a campaign landing page for the Knowledge 2025 conference",
     "WEBPAGE"),
    ("Refresh the homepage hero with updated value proposition copy",
     "WEBPAGE"),
    ("Create a new solutions page for the financial services vertical",
     "WEBPAGE"),
    ("Add a new blog post template page",
     "WEBPAGE"),

    # --- Hard cases from the Type Guide ---
    ("Update the marquee on the ITSM page with new messaging and CTA",
     "WEBPAGE"),   # Content/publishing work, not component behavior
    ("Build a new solutions page that includes a custom interactive ROI calculator",
     "WEBPAGE"),   # Page is the primary deliverable; calculator would be a separate feature
    ("Add Adobe Target personalization to the ITSM landing page",
     "CAPABILITY"), # Integration work, not page content
    ("Progressive profiling form — the core work is the data collection logic and CDP integration",
     "CAPABILITY"),
    ("Progressive profiling form — the core work is the form UI with multi-step states and validation",
     "EXPERIENCE"),
]

print(f"{'EXPECTED':<12} {'ACTUAL':<12} {'PASS':<6} DESCRIPTION")
print("-" * 90)

passed = 0
failed = 0

for description, expected in test_cases:
    actual = classify_feature(description)
    match = actual == expected
    status = "✅" if match else "❌"
    if match:
        passed += 1
    else:
        failed += 1
    print(f"{expected:<12} {actual:<12} {status:<6} {description[:60]}")

print("-" * 90)
print(f"\nResults: {passed}/{len(test_cases)} passed ({round(passed/len(test_cases)*100)}%)")