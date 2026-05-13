# intake_copilot/test_scenarios/pmm_campaign_landing_page.py
# Scenario 2 — PMM requesting a campaign landing page for financial services.
# RAW_INPUT:   unstructured stakeholder message as received
# CASE_INPUT:  ground truth — what a skilled PM would extract from a full conversation
# BOOST_INPUTS: section-specific detail the PM adds during review (feeds the Generator)

RAW_INPUT = """\
We're launching a Q3 enterprise campaign targeting financial services accounts. Need a \
landing page that speaks to compliance and risk management use cases. Should integrate with \
our existing nurture flow in Marketo. Target go-live is July 15.\
"""

CASE_INPUT = """\
Feature type: WEBPAGE

Feature description: Create a campaign landing page targeting enterprise financial services \
accounts, focused on compliance and risk management use cases. The page should present \
industry-specific value propositions, include social proof from financial services customers, \
and capture leads into the existing Marketo nurture flow. The page serves as the primary \
conversion destination for Q3 campaign media (paid search, LinkedIn ads, email outreach).

Target user: Senior compliance officers, risk management directors, and CISOs at enterprise \
financial services companies (banks, insurance companies, asset managers). These buyers \
prioritize regulatory compliance, audit readiness, and risk mitigation. They are skeptical \
of vendor claims and respond to peer validation and quantified outcomes.

Business justification: Q3 enterprise campaign targeting financial services vertical — a \
strategic growth segment. The landing page is the conversion mechanism for the campaign \
media spend. Without a dedicated, industry-specific landing page, campaign traffic lands on \
generic pages with lower conversion rates.

Success metrics: Landing page conversion rate (form fill) targeting 3–5% for paid traffic. \
MQL to SQL conversion rate for leads captured through this page. Cost per MQL from the Q3 \
campaign. Pipeline generated from financial services leads attributed to this page.

Constraints: Go-live date July 15 — approximately 8 weeks from request. Must integrate with \
existing Marketo instance (form embed, cookie tracking, nurture flow trigger). Must comply \
with financial services regulatory language requirements (no promissory claims, required \
disclaimers).

Existing context: Current campaign landing pages use a standard template. No \
financial-services-specific landing page exists. Marketo nurture flows for enterprise \
accounts are established. The company has 3–4 financial services customer logos approved \
for use.

Scope boundaries: This is the landing page only — not the full campaign (ad creative, email \
sequences, nurture flow modifications are handled by the campaign team separately). The \
landing page captures the lead and hands off to the existing nurture flow.\
"""

BOOST_INPUTS = """\
Content requirements: Page must include a financial services-specific hero section with \
compliance-focused headline. Include at minimum 2 customer case study references (logos + \
outcome stats). Compliance/risk management feature grid with 4–6 capabilities. \
Single-column form with progressive profiling (Marketo smart form showing different fields \
on return visits).

SEO/performance: Target keywords: "compliance management platform," "financial services risk \
management software." Page load time under 3 seconds. Schema markup for organization and \
product.

Design/UX: Follow the enterprise landing page template with industry-vertical color \
treatment. Above-the-fold CTA. Trust signals (SOC 2, ISO 27001 badges) visible without \
scrolling. Mobile-first design — financial services executives check email on mobile.\
"""
