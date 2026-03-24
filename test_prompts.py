# test_prompts.py
import sys
sys.path.insert(0, '.')  # Make sure Python can find your prompts folder

from prompts import capabilities, experiences, webpages, reviewer

# Check section and question counts
for name, module in [("Capabilities", capabilities), ("Experiences", experiences), ("Webpages", webpages)]:
    total = sum(len(qs) for qs in module.SECTIONS.values())
    print(f"{name}: {len(module.SECTIONS)} sections, {total} questions")

# Check rubric total
print(f"\nRubric total: {reviewer.TOTAL_POINTS} points")

# Add to test_prompts.py
print("\nStructure check:")
for name, module in [("Capabilities", capabilities), ("Experiences", experiences), ("Webpages", webpages)]:
    for section_name, questions in module.SECTIONS.items():
        assert isinstance(questions, list), f"{name} > {section_name} is not a list"
        assert all(isinstance(q, str) for q in questions), f"{name} > {section_name} contains non-strings"
print("All sections are correctly structured as lists of strings.")