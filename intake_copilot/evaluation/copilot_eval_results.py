EVAL_RESULTS = {
    "se_pricing_experience": {
        "conversation_turns": 8,
        "readiness_score": 20,
        "max_readiness": 24,
        "fields_captured": 10,
        "fields_total": 12,
        "ground_truth_captured": 5,
        "ground_truth_total": 6,
        "feature_type_guess": "CAPABILITY",
        "feature_type_correct": "EXPERIENCE",
        "feature_type_accurate": False,
        "feature_type_confidence": 0.85,
        "recommendation": "accept",
        "recommendation_appropriate": True,
        "idk_count": 1,
        "advisor_consulted": False,
        "notes": "Misclassified as CAPABILITY — copilot heard 'portal' but defaulted to CAPABILITY. PM override required. business_objective correctly separated from problem_statement after extraction tuning."
    },
    "pmm_campaign_landing_page": {
        "conversation_turns": 3,
        "readiness_score": 24,
        "max_readiness": 24,
        "fields_captured": 12,
        "fields_total": 12,
        "ground_truth_captured": 6,
        "ground_truth_total": 6,
        "feature_type_guess": "WEBPAGE",
        "feature_type_correct": "WEBPAGE",
        "feature_type_accurate": True,
        "feature_type_confidence": 0.95,
        "recommendation": "accept",
        "recommendation_appropriate": True,
        "idk_count": 0,
        "advisor_consulted": False,
        "notes": "Cleanest run. PMM provided detailed answers across all fields. Copilot correctly adapted to gap-filling strategy — asked implementation questions, not basic extraction."
    },
    "eng_graphql_schema": {
        "conversation_turns": 7,
        "readiness_score": 20,
        "max_readiness": 24,
        "fields_captured": 10,
        "fields_total": 12,
        "ground_truth_captured": 6,
        "ground_truth_total": 6,
        "feature_type_guess": "CAPABILITY",
        "feature_type_correct": "CAPABILITY",
        "feature_type_accurate": True,
        "feature_type_confidence": 0.90,
        "recommendation": "accept",
        "recommendation_appropriate": True,
        "idk_count": 0,
        "advisor_consulted": False,
        "notes": "Reverse extraction worked — copilot pulled business justification from a reluctant technical stakeholder. Eng lead pushed back ('can we skip the business case questions') and copilot handled it gracefully."
    }
}

SUMMARY = {
    "avg_turns": 6.0,
    "avg_readiness": 21.3,
    "avg_ground_truth_capture": "5.7 / 6.0 (94%)",
    "feature_type_accuracy": "2 / 3 (67%)",
    "recommendation_accuracy": "3 / 3 (100%)",
    "key_findings": [
        "Adaptive question depth works — 3 turns for high-knowledge PMM, 7-8 for lower-knowledge SE and reverse-extraction Eng lead",
        "Extraction quality is high — 94% of ground truth fields captured across scenarios",
        "Feature type classification is the weakest link — 67% accuracy, but PM override at Stage 5 mitigates this by design",
        "Two-call split (conversation + extraction) eliminated the stub response bug entirely",
        "The 'I don't know' handling works — copilot adjusts depth and reports knowledge boundary to PM",
        "Reverse extraction (pulling business context from technical stakeholders) is a validated pattern"
    ]
}
