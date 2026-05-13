# intake_copilot/test_scenarios/se_pricing_experience.py
# Scenario 1 — Sales Engineer requesting a self-service pricing portal experience.
# RAW_INPUT:   unstructured stakeholder message as received
# CASE_INPUT:  ground truth — what a skilled PM would extract from a full conversation
# BOOST_INPUTS: section-specific detail the PM adds during review (feeds the Generator)

RAW_INPUT = """\
Hey, one of my accounts (Meridian Healthcare) is up for renewal in Q3 and they've been \
asking about being able to see their pricing directly on the website instead of having to \
go through their rep every time. Can we do something about this? They're a $2M ARR account.\
"""

CASE_INPUT = """\
Feature type: EXPERIENCE

Feature description: Build a self-service pricing experience on the customer portal that \
allows existing customers to view their current contract pricing, including per-product \
rates and volume tier thresholds, without contacting their account representative. The \
experience should be accessible from the authenticated customer dashboard and display \
pricing specific to the customer's active contract and segment.

Target user: Existing enterprise customers who have active contracts and want to reference \
their pricing during internal budgeting, procurement renewals, or vendor evaluations. \
Primary use case is the renewal cycle when customers need pricing visibility to prepare \
internal approvals.

Business justification: Directly supports account retention. Meridian Healthcare ($2M ARR, \
Q3 renewal) is the originating request, but the need is common across the enterprise segment. \
Self-service pricing reduces rep dependency, shortens the renewal preparation cycle, and \
removes a friction point that competitors may not have.

Success metrics: Reduction in "what's my pricing" support tickets and rep inquiries. \
Increase in portal login frequency during renewal windows. Retention rate for accounts that \
use the self-service pricing feature vs. those that don't.

Constraints: Must respect contract confidentiality — customers can only see their own \
pricing. Pricing data must be sourced from the contract management system (real-time or \
daily sync). Must handle edge cases: multi-year contracts with annual escalators, \
volume-based tiers, custom negotiated rates.

Existing context: Customers currently contact their account rep or submit a support ticket \
to get pricing information. The customer portal exists but has no pricing module. The \
contract management system holds the source data.\
"""

BOOST_INPUTS = """\
Acceptance criteria: Portal pricing display must match CMS source data within 24 hours. \
Must support at least 3 pricing structures: flat rate, volume tier, and custom negotiated. \
Must show contract expiration date alongside pricing.

Technical requirements: SSO-authenticated portal session required. Pricing API must return \
data in under 2 seconds. Mobile-responsive layout required — 40% of portal traffic is mobile \
during renewal windows.

Edge cases: Handle expired contracts (show "contact your rep" message, not stale pricing). \
Handle mid-contract amendments (show most recent amendment pricing). Handle \
multi-subsidiary accounts (pricing per subsidiary, not consolidated).\
"""
