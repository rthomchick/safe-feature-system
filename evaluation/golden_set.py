# evaluation/golden_set.py
# Week 8 baseline — established 2026-03-23
# Run against the full pipeline to verify quality hasn't regressed

GOLDEN_SET = [
    {
        "id": "cap_001",
        "name": "Buying Group Identification",
        "type": "CAPABILITY",
        "description": (
            "Build a buying group identification capability that classifies web visitors "
            "into buying group roles (Champion, Economic Buyer, Influencer, User, Ratifier) "
            "based on their behavioral signals on servicenow.com"
        ),
        "expected_routing": "CAPABILITY",
        "baseline_original_score": 71,
        "baseline_final_score": 93,
        "min_final_score": 88,        # Alert if drops below this
        "target_final_score": 90,     # Leadership review threshold
        "sections_must_pass": [       # Must be >= 75% after improvement
            "Feature Definition & Objective",
            "Scope, Out of Scope, and Dependencies",
            "User Stories & Acceptance Criteria",
        ],
        "notes": "Rich technical notes. Strong without boost inputs. "
                 "Copywriting and Feature Definition benefit from boost inputs.",
    },
    {
        "id": "web_001",
        "name": "Financial Services Solutions Page",
        "type": "WEBPAGE",
        "description": (
            "Create a new solution page for the financial services vertical on "
            "servicenow.com targeting Economic Buyers and Champions at banks and "
            "insurance companies"
        ),
        "expected_routing": "WEBPAGE",
        "baseline_original_score": 71,
        "baseline_final_score": 94,
        "min_final_score": 88,
        "target_final_score": 90,
        "sections_must_pass": [
            "Feature Definition & Objective",
            "Scope, Out of Scope, and Dependencies",
            "User Stories & Acceptance Criteria",
        ],
        "notes": "Requires boost inputs for SEO, Campaigns, Studio, Engineering "
                 "to reach 90+. Content strategy notes are strong.",
    },
    {
        "id": "exp_001",
        "name": "Progressive Profiling Form Component",
        "type": "EXPERIENCE",
        "description": (
            "Build a progressive profiling form component for servicenow.com that "
            "displays a shortened form for known users with pre-filled fields, and a "
            "standard form for net-new visitors, using Adobe Target for audience "
            "targeting and Arc Design System for all UI components"
        ),
        "expected_routing": "EXPERIENCE",
        "baseline_original_score": None,  # Fill in after Case 3 run
        "baseline_final_score": None,     # Fill in after Case 3 run
        "min_final_score": 88,
        "target_final_score": 90,
        "sections_must_pass": [
            "Feature Definition & Objective",
            "Scope, Out of Scope, and Dependencies",
            "User Stories & Acceptance Criteria",
        ],
        "notes": "Rich component state notes. Router must classify as EXPERIENCE "
                 "not CAPABILITY — both describe progressive profiling.",
    },
]