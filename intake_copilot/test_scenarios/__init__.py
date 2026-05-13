from intake_copilot.test_scenarios.se_pricing_experience import (
    BOOST_INPUTS as SE_BOOST_INPUTS,
    CASE_INPUT as SE_CASE_INPUT,
    RAW_INPUT as SE_RAW_INPUT,
)
from intake_copilot.test_scenarios.pmm_campaign_landing_page import (
    BOOST_INPUTS as PMM_BOOST_INPUTS,
    CASE_INPUT as PMM_CASE_INPUT,
    RAW_INPUT as PMM_RAW_INPUT,
)
from intake_copilot.test_scenarios.eng_graphql_schema import (
    BOOST_INPUTS as ENG_BOOST_INPUTS,
    CASE_INPUT as ENG_CASE_INPUT,
    RAW_INPUT as ENG_RAW_INPUT,
)

SCENARIOS: list[dict] = [
    {
        "name": "SE: Pricing Experience",
        "persona": "sales_engineer",
        "expected_type": "EXPERIENCE",
        "raw_input": SE_RAW_INPUT,
        "case_input": SE_CASE_INPUT,
        "boost_inputs": SE_BOOST_INPUTS,
    },
    {
        "name": "PMM: Campaign Landing Page",
        "persona": "pmm",
        "expected_type": "WEBPAGE",
        "raw_input": PMM_RAW_INPUT,
        "case_input": PMM_CASE_INPUT,
        "boost_inputs": PMM_BOOST_INPUTS,
    },
    {
        "name": "Eng: GraphQL Schema",
        "persona": "eng_lead",
        "expected_type": "CAPABILITY",
        "raw_input": ENG_RAW_INPUT,
        "case_input": ENG_CASE_INPUT,
        "boost_inputs": ENG_BOOST_INPUTS,
    },
]
