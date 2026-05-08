# evaluation/golden_set.py
# Day 2 golden set — 6 entries across 3 feature types × 2 quality levels.
#
# Each entry has:
#   id                  — unique identifier
#   name                — human-readable label
#   feature_type        — CAPABILITY | EXPERIENCE | WEBPAGE
#   description         — feature description passed to classify_feature()
#   section_answers     — dict[section_name, answer_text] passed to generate_feature_spec()
#                         Keys must match the section names in the corresponding prompts module
#   expected_min_score  — eval pass threshold (reviewer total_score must meet or exceed this)
#
# Quality levels:
#   bare     — section_answers from raw notes only (Draft Answerer output simulation)
#              Target: ~70. Min threshold: 65.
#   boosted  — section_answers enriched with boost inputs merged in
#              Target: ~85. Min threshold: 80.
#
# Test cases based on Week 8 validation (cap_001, web_001, exp_001).
# Source notes: evaluation/test_case_*.md
# Boost inputs: evaluation/boost_inputs_case*.md

GOLDEN_SET = [

    # ══════════════════════════════════════════════════════════════════════════
    # CAPABILITY — Buying Group Identification
    # ══════════════════════════════════════════════════════════════════════════

    {
        "id": "cap_001_bare",
        "name": "Buying Group Identification (bare)",
        "feature_type": "CAPABILITY",
        "description": (
            "Build a buying group identification capability that classifies web visitors "
            "into buying group roles (Champion, Economic Buyer, Influencer, User, Ratifier) "
            "based on their behavioral signals on servicenow.com"
        ),
        "expected_min_score": 65,
        "section_answers": {

            "Strategy & Purpose": """\
This capability solves the problem of serving generic content to all web visitors when
role-appropriate personalization could meaningfully improve engagement and pipeline conversion.
By classifying visitors into buying group roles — Champion, Economic Buyer, Influencer, User,
and Ratifier — we can deliver content tailored to each role's priorities.

Primary users are ServiceNow marketing personalization systems (Adobe Target for content
targeting), Marketing Ops (Marketo lead enrichment), and Sales Ops (account-level buying
group insights). End beneficiaries are prospects who receive more relevant content.

Classification produces a confidence score (0–100) per role. The system surfaces the highest
confidence role for targeting. A visitor can have scores across multiple roles simultaneously.

Target Account List (TAL) accounts (48,000 accounts) receive priority classification scoring.
Visitors from non-TAL companies receive a lighter-weight classification pass.

This is a platform capability intended for reuse across multiple downstream experiences:
personalized content on product pages, email segmentation in Marketo, and Adobe Target
audience definitions. Reusability requires classification output to be stored in Tealium CDP
as visitor profile attributes accessible to all connected downstream systems.

[NEEDS INPUT: Feature owner name, PM name, tech lead, key reviewers]
[NEEDS INPUT: Quantitative KPI targets and parent Epic link]
""",

            "Design & User Experience": """\
This is a backend classification capability — it operates entirely headless with no
user-facing UI components, visual design, or front-end rendering.

Classification output surfaces through three downstream systems:
- Adobe Target: uses confidence scores as audience segment definitions for content delivery
- Tealium CDP: stores role confidence scores as visitor profile attributes
- Marketo: lead records enriched with the highest-confidence role classification

No responsive design, wireframes, states, or animations are required. The capability has
no interaction model — it processes signals and outputs confidence scores.

Design guidelines and accessibility considerations are not applicable for this capability.
""",

            "Content & Localization": """\
Content served to visitors is not managed within this capability — the classification engine
is a signal-processing system. Content delivery is handled by Adobe Target, which consumes
the role classification as audience input and serves type-appropriate content variants.

Role classification is derived from behavioral signals:
- Page visit history (via Tealium CDP)
- Content category interactions (tagged in AEM by buying group role)
- Job title from Marketo lead record (for known/identified users)
- Referral source and UTM parameters
- Form submission history

No localization or translation requirements for the classification engine itself.
Content variants served by Adobe Target are managed separately within AEM.

Fallback behavior: if classification confidence is below threshold (TBD), default to
serving generic content without role targeting. No error state shown to visitors.
""",

            "SEO & Analytics": """\
This is a backend capability — not a user-facing page. SEO indexing is not applicable.
No keywords, meta tags, or structured data requirements.

Analytics tracking is required to measure classification performance:
- Classification events should fire via Tealium CDP when role scores are assigned
- Adobe Target: classification used as audience segment for A/B and personalization tests
- Marketo: lead record enrichment with highest-confidence role classification

[NEEDS INPUT: Specific analytics event names and schema (event name, properties, destinations)]
[NEEDS INPUT: KPI dashboard location and ownership]
[NEEDS INPUT: UTM parameter strategy for referral source classification signal]
[NEEDS INPUT: GDPR/CCPA compliance status for behavioral signal processing]
""",

            "Engineering & Technical Requirements": """\
Tech stack dependencies:
- Tealium CDP: event collection, identity stitching, visitor profile storage
  — classification output stored as profile attributes in visitor profile
- Adobe Target: consumes role classification as audience segment for content targeting
- Marketo: lead record enrichment with primary role classification
- AEM: content tagging by buying group role to generate behavioral signals
- ServiceNow TAL (Target Account List): 48,000 priority accounts for enhanced scoring

Classification approach:
- Confidence score (0–100) per role, not binary assignment
- Multi-role scoring: a visitor can carry confidence scores across multiple roles
- Highest-confidence role used for targeting activation
- TAL accounts: full classification pass with higher signal weighting
- Non-TAL visitors: lighter classification pass

Architecture decision pending: real-time classification vs. 24-hour batch update of
Tealium profiles. Real-time preferred to support Adobe Target use case.

No custom backend API endpoint planned in V1 — classification processing runs within
Tealium's data enrichment layer using configured signal rules.

[NEEDS INPUT: Content model / output data schema (field names, types, destinations)]
[NEEDS INPUT: Classification confidence threshold for targeting activation]
""",

            "Accessibility & Compliance": """\
This is a backend capability with no user-facing UI — standard WCAG accessibility
requirements do not apply.

Compliance considerations:
- GDPR/CCPA: this capability processes behavioral data (page visits, interactions, referral
  sources). Legal and privacy team review is required to confirm the existing CDP consent
  framework covers this use case before launch.
- Classification engine stores confidence scores and behavioral signal aggregates only —
  no personally identifiable information is stored within the engine itself.

[NEEDS INPUT: Privacy team sign-off status on data retention policy for classification profiles]
[NEEDS INPUT: GDPR/CCPA review outcome confirmation]
""",

            "Testing & QA": """\
QA team: No QA team formally assigned yet. Personalization pod to identify QA owner.

Acceptance criteria:
- Classification confidence scores must be reproducible within ±5 points across
  identical signal sets (deterministic scoring for the same visitor signal combination)
- TAL account lookup must correctly identify accounts within the 48,000-account TAL
- Adobe Target audience segments must correctly activate when confidence score
  meets the activation threshold

Testing strategies needed:
- Unit tests: signal weighting rules and confidence score calculation
- Integration tests: Tealium CDP event ingestion → classification → profile attribute write
- End-to-end tests: classification → Adobe Target audience → content variant delivery

[NEEDS INPUT: QA owner assignment]
[NEEDS INPUT: Confidence score activation threshold value for testing]
""",

            "Publishing & Release Management": """\
Timeline: Q3 PI target. No hard deadline confirmed as of notes date.

Architecture decision pending before deployment planning can be completed:
- Real-time classification: preferred for Adobe Target use case (content delivered
  on page load requires audience resolution in real time)
- 24-hour batch update: simpler implementation, lower real-time processing requirements

Deployment path (draft):
1. Tealium CDP signal rule configuration + testing
2. Adobe Target audience segment configuration
3. Marketo field mapping for role enrichment
4. AEM content tagging validation (existing tags used as signals)
5. QA validation on staging environment
6. Soft launch on limited TAL account segment
7. Full rollout

[NEEDS INPUT: Feature flag requirement for controlled rollout]
[NEEDS INPUT: Rollback plan for classification engine]
[NEEDS INPUT: Real-time vs. batch decision outcome]
""",
        },
    },

    {
        "id": "cap_001_boosted",
        "name": "Buying Group Identification (boosted)",
        "feature_type": "CAPABILITY",
        "description": (
            "Build a buying group identification capability that classifies web visitors "
            "into buying group roles (Champion, Economic Buyer, Influencer, User, Ratifier) "
            "based on their behavioral signals on servicenow.com"
        ),
        "expected_min_score": 80,
        "section_answers": {

            "Strategy & Purpose": """\
This capability solves the problem of serving generic content to all web visitors when
role-appropriate personalization could meaningfully improve engagement and pipeline conversion.
By classifying visitors into buying group roles — Champion, Economic Buyer, Influencer, User,
and Ratifier — we can deliver content tailored to each role's priorities.

Feature Owner: Richard (Senior PM, Personalization)
Tech Lead: TBD — Personalization pod owns implementation
Key Reviewers: Personalization pod leads, Marketing Ops, Sales Ops

Quantitative targets:
- 80% of TAL account visitors classified into at least one buying group role within 90 days
- Confidence score threshold of 60+ required for content targeting activation
- Reduce "unknown visitor" rate on TAL accounts from current baseline by 50%
- Adobe Target A/B test: role-targeted content vs. generic — target 15% improvement in
  engagement metrics (time on page, CTA clicks)

Parent Epic: Buying Group Intelligence — Q3 Account-Based Experience initiative.
Directly supports ServiceNow's TAL strategy for 48,000 priority accounts.
Strategic fit: enables downstream personalization for all 5 buying group roles and
accelerates pipeline via role-appropriate content delivery.

Primary users are Adobe Target (content targeting), Marketing Ops (Marketo enrichment),
and Sales Ops (account-level insights). Classification produces a confidence score (0–100)
per role; highest-confidence role used for targeting. A visitor can carry multiple role scores.

TAL accounts (48,000) receive priority classification. Non-TAL visitors receive a
lighter classification pass.

This is a platform capability for reuse across personalized product pages, email
segmentation in Marketo, and Adobe Target audience definitions. Classification output stored
in Tealium CDP as visitor profile attributes accessible to all connected systems.
""",

            "Design & User Experience": """\
This is a backend classification capability — it operates entirely headless with no
user-facing UI components, visual design, or front-end rendering.

Classification output surfaces through three downstream systems:
- Adobe Target: uses confidence scores as audience segment definitions for content delivery
- Tealium CDP: stores role confidence scores as visitor profile attributes
- Marketo: lead records enriched with the highest-confidence role classification

No responsive design, wireframes, states, or animations are required. This is a headless
signal-processing engine. All design concerns belong to downstream EXPERIENCE features
that consume the classification output.
""",

            "Content & Localization": """\
Content delivery is handled by Adobe Target, not within this capability. The classification
engine processes signals and outputs confidence scores consumed downstream.

Signal sources (content classification drivers):
- Page visit history (via Tealium CDP)
- Content category interactions (tagged in AEM by buying group role)
- Job title from Marketo lead record (for identified users)
- Referral source and UTM parameters
- Form submission history

Tone and voice: Professional and data-driven — consistent with ServiceNow brand standards.
Documentation and UI copy (for internal stakeholder materials) should avoid jargon and
write for cross-functional audiences including engineering, marketing, and sales ops.

Key messages for documentation and internal stakeholders:
- "Classify every visitor. Target every role." — primary value prop
- Classification is based on behavioral signals only — no PII stored in the engine
- Confidence scores (0–100) power personalization — only activate targeting at 60+ threshold

Legal and compliance:
- GDPR/CCPA review required before launch — classification engine processes behavioral data;
  confirm with legal that existing consent framework covers this use case
- Privacy team must sign off on data retention policy for classification profiles
- No PII stored in the classification engine — only behavioral signal aggregates and scores

Approval workflow: Legal review → Privacy team sign-off → PM approval → launch

No localization or translation requirements for the classification engine itself.
""",

            "SEO & Analytics": """\
This is a backend capability — not a user-facing page. SEO indexing is not applicable.
No keywords, meta tags, canonical URLs, or structured data requirements.

Analytics tracking requirements (via Tealium CDP):
Event schema — classification output:
- visitor_classified: {role, confidence_score, account_id, is_TAL}
  — fires when role confidence score is assigned or updated

Adobe Target integration:
- Classification used as audience segment for content targeting
- Activation threshold: confidence score ≥ 60

Marketo integration:
- Lead records enriched with highest-confidence role classification
- Improves email segmentation accuracy for nurture programs

KPI dashboard: Tableau (existing web analytics instance)
- Add "Buying Group Classification" view to existing Tableau dashboard
- Track: % TAL visitors classified, confidence score distribution, classification-to-activation rate

UTM parameters: capture referral source as classification signal (utm_source, utm_medium)

GDPR/CCPA: classification based on behavioral signals only, no PII stored in classification
engine — compliant with existing CDP consent framework (confirm with legal before launch)
""",

            "Engineering & Technical Requirements": """\
Tech stack dependencies:
- Tealium CDP: event collection, identity stitching, visitor profile storage
  — classification output stored as profile attributes accessible to all connected systems
- Adobe Target: consumes role classification as audience segment (confidence score ≥ 60 threshold)
- Marketo: lead record enrichment with primary role classification
- AEM: content tagging by buying group role (existing tag taxonomy used as signal source)
- ServiceNow TAL: 48,000 priority accounts for enhanced scoring priority

Classification approach:
- Confidence score (0–100) per role, not binary assignment
- Highest-confidence role used for targeting activation
- TAL accounts: full classification with higher signal weighting
- Non-TAL visitors: lighter classification pass

Architecture: real-time classification preferred over 24-hour batch update to support
Adobe Target content delivery on page load. Decision pending confirmation.

Content model — classification output schema:
| Field                    | Type           | Source          | Destination                |
|--------------------------|----------------|-----------------|---------------------------|
| visitor_id               | string         | Tealium CDP     | All systems               |
| account_id               | string         | TAL lookup      | Marketo, Target           |
| is_TAL                   | boolean        | TAL lookup      | Target audiences          |
| role_champion            | integer 0–100  | Signal engine   | Tealium, Target           |
| role_economic_buyer      | integer 0–100  | Signal engine   | Tealium, Target           |
| role_influencer          | integer 0–100  | Signal engine   | Tealium, Target           |
| role_user                | integer 0–100  | Signal engine   | Tealium, Target           |
| role_ratifier            | integer 0–100  | Signal engine   | Tealium, Target           |
| primary_role             | string         | Derived         | Marketo enrichment        |
| classification_timestamp | datetime       | System          | All systems               |

Post-launch: monitor classification accuracy monthly; retrain signal weights quarterly
based on Marketo lead-to-opportunity conversion data.
""",

            "Accessibility & Compliance": """\
This is a backend capability with no user-facing UI — standard WCAG accessibility
requirements do not apply to the engine itself.

Compliance requirements:
- GDPR/CCPA: legal review required before launch. Classification engine processes behavioral
  data; existing CDP consent framework must be confirmed to cover this use case.
- Privacy team sign-off required on data retention policy for classification profiles.
- No PII stored in the engine — only behavioral signal aggregates and confidence scores.

Approval workflow: Legal review → Privacy team sign-off → PM approval → launch

Performance target: classification must complete within 200ms to support real-time
Adobe Target audience evaluation on page load.

Taxonomy: classify as capability/personalization/buying-group in AEM taxonomy.
""",

            "Testing & QA": """\
QA owner: Personalization pod to identify QA owner (not yet assigned).

Acceptance criteria:
- Classification confidence scores must be reproducible within ±5 points across
  identical signal sets (deterministic scoring)
- TAL account lookup correctly identifies accounts within the 48,000-account TAL
- Adobe Target audience segments activate correctly when confidence ≥ 60 threshold is met
- Classification latency: ≤ 200ms for real-time Adobe Target evaluation

Testing strategies:
- Unit tests: signal weighting rules and confidence score calculation per role
- Integration tests: Tealium CDP event ingestion → classification → profile attribute write
- End-to-end tests: classification → Adobe Target audience → content variant delivery
- Performance tests: confirm ≤ 200ms classification latency under expected load
- Regression tests: monthly accuracy checks post-launch; quarterly signal weight retraining

Edge cases:
- Visitor with equal confidence scores across multiple roles (tie-breaking logic)
- Non-TAL visitor with high intent signals (should still receive lighter classification)
- Tealium CDP unavailability (fallback to generic content, no error shown to visitor)
- New visitor with no behavioral history (cold start classification behavior)
""",

            "Publishing & Release Management": """\
Timeline: Q3 PI target. No hard deadline confirmed.

Architecture decision: real-time classification preferred over 24-hour batch update
to support Adobe Target page-load content delivery. Decision pending final confirmation.

Deployment path:
1. Tealium CDP signal rule configuration + unit tests
2. Adobe Target audience segment configuration (confidence score thresholds)
3. Marketo field mapping for primary role enrichment
4. AEM content tagging validation (existing tags used as signals)
5. QA validation on staging: signal ingestion, score computation, profile write
6. Legal/privacy review of data processing and consent coverage
7. Soft launch targeting a limited TAL account segment
8. Full rollout with monitoring

Feature flag: required for controlled rollout and instant rollback capability.
Rollback plan: disable classification signal processing in Tealium; Adobe Target
falls back to generic content audiences. No user-visible impact.

Post-launch monitoring: Tableau dashboard tracking classification coverage,
confidence score distribution, and Adobe Target activation rate.
Classification accuracy review: monthly. Signal weight retraining: quarterly.
""",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # WEBPAGE — Financial Services Solutions Page
    # ══════════════════════════════════════════════════════════════════════════

    {
        "id": "web_001_bare",
        "name": "Financial Services Solutions Page (bare)",
        "feature_type": "WEBPAGE",
        "description": (
            "Create a new solution page for the financial services vertical on "
            "servicenow.com targeting Economic Buyers and Champions at banks and "
            "insurance companies"
        ),
        "expected_min_score": 65,
        "section_answers": {

            "Content Strategy & Purpose": """\
Primary objective: Lead generation for the financial services vertical. Financial services
is a Q3 priority vertical. We need a dedicated landing page that speaks to FS-specific
pain points — currently FS prospects are sent to the generic solutions page where
conversion is below average for this segment.

Target audience:
- Economic Buyers: CIOs, CTOs, COOs at banks, insurance companies, asset managers
- Champions: IT directors, digital transformation leads, operations managers
- Buyer journey stage: mid-funnel (solution evaluation)

Key messages:
- ServiceNow reduces operational risk and improves compliance readiness for regulated industries
- Proven at 8 of the top 10 global banks
- FFIEC, SOC2, and ISO 27001 compliance support built in

CTAs:
- Primary: "Talk to a Financial Services Expert" (form, routed to FS sales team)
- Secondary: "See the ROI Calculator" (links to existing live ROI tool)
- Tertiary: "Download the FS Reference Architecture" (gated PDF asset)

Problem solved for user: single destination that addresses FS-specific compliance,
risk, and operational concerns — without requiring FS prospects to self-navigate
from a generic solutions page.

[NEEDS INPUT: Feature owner, PM name, tech lead, and key reviewer names/roles]
[NEEDS INPUT: Quantitative KPI targets and parent Epic link]
""",

            "Studio & Design": """\
Use existing solutions page template — no new component development required.
Page structure:
- Hero: FS imagery (Brand team to source), headline + subhead + primary CTA
- Value props: 3-column layout using existing VP component
- Logo bar: 6 approved FS customer logos (assets available)
- Customer quote: Zurich Insurance (approved quote on file)
- Asset download: FS Reference Architecture PDF (gated, Marketo form)

No custom animations or interactive elements beyond existing template components.
All components use existing Arc Design System implementations.

[NEEDS INPUT: WCAG 2.2 compliance confirmation, Core Web Vitals targets, responsive
breakpoints, AEM taxonomy tagging requirements]
""",

            "Copywriting": """\
Tone and voice: Professional and authoritative — appropriate for Economic Buyers
(CIOs, CTOs, COOs) at regulated financial institutions.

Key messages:
- ServiceNow reduces operational risk and improves compliance readiness for regulated industries
- Proven at 8 of the top 10 global banks
- FFIEC, SOC2, and ISO 27001 compliance support built in

Existing assets: Zurich Insurance case study (approved), FS solution brief (PDF),
ROI calculator (already live).

Legal and compliance: Legal review required for compliance claims (FFIEC, SOC2,
ISO 27001 references) before launch. FS sales team must approve messaging.
Brand team to source hero imagery.

Approval workflow: FS sales team messaging approval → Legal review for compliance
claims → Brand team imagery approval → publish.

[NEEDS INPUT: Brand voice guidelines and full copy drafts]
[NEEDS INPUT: Whether any copy requires separate marketing communications review]
""",

            "SEO & Analytics": """\
Target keywords:
- Primary: "financial services IT service management"
- Secondary: "bank digital transformation platform"
- Tertiary: "insurance workflow automation"

URL: servicenow.com/solutions/financial-services (new page)

[NEEDS INPUT: Meta title and meta description]
[NEEDS INPUT: Internal linking strategy — which existing pages should link here]
[NEEDS INPUT: Schema markup requirements (Organization, WebPage, etc.)]
[NEEDS INPUT: UTM parameters for campaign tracking (Sibos conference, paid search)]
[NEEDS INPUT: KPI dashboard location (Tableau, Google Analytics, Adobe Analytics)]
[NEEDS INPUT: Specific analytics events to track (CTA clicks, PDF download, logo bar)]
[NEEDS INPUT: GDPR/CCPA considerations for UK/APAC geo rollout (hreflang tags)]
Post-campaign plan: after Sibos, redirect to permanent FS solutions page.
""",

            "Engineering & Publishing": """\
Timeline: Must be live before Sibos conference (October). Content freeze 2 weeks prior.
Geo rollout: US first, then UK and APAC in follow-on sprint.
QA: Gryffindors team — standard QA process.

No new components required — all use existing solutions page template components.
No custom front-end logic or embed code required from development team.

Dependencies:
- Brand team: source hero imagery
- Legal team: review and approve compliance claims before publish
- FS sales team: approve messaging
- Marketo: gated form for FS Reference Architecture PDF download

[NEEDS INPUT: Full content model table (components, fields, field types, AEM component names)]
[NEEDS INPUT: Specific QA scope (layout checks, content accuracy, CTA routing, analytics)]
[NEEDS INPUT: A/B testing plan (V1 or future roadmap)]
[NEEDS INPUT: AEM taxonomy tagging structure for this page]
[NEEDS INPUT: Rollback plan if publish fails]
""",
        },
    },

    {
        "id": "web_001_boosted",
        "name": "Financial Services Solutions Page (boosted)",
        "feature_type": "WEBPAGE",
        "description": (
            "Create a new solution page for the financial services vertical on "
            "servicenow.com targeting Economic Buyers and Champions at banks and "
            "insurance companies"
        ),
        "expected_min_score": 80,
        "section_answers": {

            "Content Strategy & Purpose": """\
Primary objective: Lead generation for the financial services vertical. Financial services
is a Q3 priority vertical. We need a dedicated landing page that speaks to FS-specific
pain points — currently FS prospects are sent to the generic solutions page where
conversion is below average for this segment.

Feature Owner: Richard (Senior PM, Web Experience)
Tech Lead: TBD — Web Engineering team
Key Reviewers: FS Sales team lead (messaging approval), Legal (compliance claims),
Brand team (hero imagery), Gryffindors QA lead

Target audience:
- Economic Buyers: CIOs, CTOs, COOs at banks, insurance companies, asset managers
- Champions: IT directors, digital transformation leads, operations managers
- Buyer journey stage: mid-funnel (solution evaluation)

Key messages:
- ServiceNow reduces operational risk and improves compliance readiness for regulated industries
- Proven at 8 of the top 10 global banks
- FFIEC, SOC2, and ISO 27001 compliance support built in

CTAs in priority order:
1. "Talk to a Financial Services Expert" — form, routes to FS sales team (P0)
2. "See the ROI Calculator" — links to existing live tool (P1)
3. "Download the FS Reference Architecture" — gated PDF asset (P2)

KPI targets:
- Primary CTA form conversion: 3–5%
- MQL volume from page: establish 90-day baseline, target 20% above generic page
- Bounce rate: target below 50% (vs. generic solutions page benchmark)
- Time on page: target 2:30+ average
- Pipeline influenced: track Salesforce opportunities with this page in the journey

Parent Epic: Financial Services Vertical Expansion — Q3 priority initiative.
Strategic fit: dedicated FS page eliminates generic solutions page fallback for
8 of the top 10 global bank prospects — directly supports Q3 pipeline targets.
""",

            "Studio & Design": """\
Use existing solutions page template — no new component development required.
Page structure:
- Hero: FS imagery (Brand team to source), headline + subhead + primary CTA
- Value props: 3-column layout using existing VP component
- Logo bar: 6 approved FS customer logos (assets available)
- Customer quote: Zurich Insurance (approved quote on file)
- Asset download: FS Reference Architecture PDF (gated, Marketo form)

WCAG 2.2 compliance required — use existing Arc Design System components.
Responsive: desktop + mobile (use existing template breakpoints).
Performance: Core Web Vitals passing required before launch.
No custom animations or interactive elements beyond existing template components.

Taxonomy: tag as solutions/financial-services in AEM taxonomy system.
Performance: Core Web Vitals passing required before launch. No negative impact
on LCP or CLS from any added imagery or custom code.
""",

            "Copywriting": """\
Tone and voice: Professional and authoritative — appropriate for Economic Buyers
(CIOs, CTOs, COOs) at regulated financial institutions. Consistent with ServiceNow
brand standards for enterprise solutions pages.

Key messages:
- ServiceNow reduces operational risk and improves compliance readiness for regulated industries
- Proven at 8 of the top 10 global banks
- FFIEC, SOC2, and ISO 27001 compliance support built in

Existing assets available:
- Zurich Insurance case study (approved quote on file)
- FS solution brief (PDF)
- ROI calculator (already live — link as secondary CTA)

Legal and compliance:
- Legal review required for compliance claims (FFIEC, SOC2, ISO 27001 references)
- FS sales team must approve messaging before launch
- Brand team to source and approve hero imagery

Approval workflow: FS sales team messaging approval → Legal review for compliance
claims → Brand team imagery approval → PM sign-off → QA → publish.

All copy should align with existing ServiceNow brand voice guidelines.
No separate marketing communications review required beyond the approval workflow above.
""",

            "SEO & Analytics": """\
Target keywords:
- Primary: "financial services IT service management"
- Secondary: "bank digital transformation platform"
- Tertiary: "insurance workflow automation"

SEO strategy:
- Canonical URL: servicenow.com/solutions/financial-services
- Meta title: Financial Services IT Solutions | ServiceNow
- Meta description: Reduce operational risk and improve compliance readiness.
  Proven at 8 of the top 10 global banks. FFIEC, SOC2, ISO 27001 support.
- Internal linking: link from ITSM product page, financial services blog posts
- Schema markup: Organization + WebPage schema
- Image optimization: alt text for all images, compressed hero asset

Analytics and KPIs:
- Track: CTA form conversion rate, bounce rate, time on page, scroll depth
- Custom events: CTA clicks (all 3), logo bar interactions, PDF download
- UTM parameters: utm_campaign=sibos-2025 for Sibos conference traffic
- KPI dashboard: existing Tableau web analytics dashboard — add FS page view

GDPR/CCPA: page uses existing consent framework — no additional requirements.
UK and APAC geo rollout will require hreflang tags — add in follow-on sprint.
Post-campaign: after Sibos, redirect to permanent FS solutions page (no expiry).
""",

            "Engineering & Publishing": """\
Timeline:
- Live before Sibos conference (October 2025) — hard deadline
- Content freeze: 2 weeks prior to Sibos
- US launch first, then UK (servicenow.com/uk/) and APAC in follow-on sprint

Geo rollout:
- Phase 1: US (servicenow.com/solutions/financial-services)
- Phase 2: UK (/uk/solutions/financial-services) — hreflang required
- Phase 3: APAC — markets TBD

QA: Gryffindors team — standard QA process
QA scope: layout accuracy, content accuracy, CTA functionality, form routing to FS sales
team, analytics tracking validation, mobile responsiveness, Core Web Vitals

Legal review required: FFIEC, SOC2, ISO 27001 compliance claims must be approved
by legal before launch.

Content model:
| Component       | Fields                                             | Type           | Notes                        |
|-----------------|----------------------------------------------------|----------------|------------------------------|
| Hero            | Headline, Subhead, CTA label, CTA URL, Image       | AEM component  | Brand team sources image      |
| Value Props     | Icon ×3, Title ×3, Body ×3                         | AEM component  | Existing VP component         |
| Logo Bar        | Logo image ×6, Alt text ×6                         | AEM component  | 6 approved FS logos           |
| Customer Quote  | Quote text, Attribution, Logo                      | AEM component  | Zurich Insurance              |
| Asset Download  | Headline, Description, CTA label, Asset URL        | Marketo gated  | FS Reference Architecture PDF |
| SEO             | Meta title, Meta description, Canonical URL        | AEM page props |                               |

Sibos campaign dependencies:
- All Sibos campaign traffic tagged: utm_campaign=sibos-2025, utm_source per channel
- Paid campaign: ads targeting FS titles (CIO, CTO, COO) — landing page is this page
- SEM: paid search on target keywords during Sibos conference week

No new components required — all use existing solutions page template components.
No custom front-end logic or embed code required.
A/B testing: not in V1 — add to V2 roadmap.
Rollback plan: unpublish in AEM; 404 redirects to generic solutions page.
""",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # EXPERIENCE — Progressive Profiling Form Component
    # ══════════════════════════════════════════════════════════════════════════

    {
        "id": "exp_001_bare",
        "name": "Progressive Profiling Form Component (bare)",
        "feature_type": "EXPERIENCE",
        "description": (
            "Build a progressive profiling form component for servicenow.com that "
            "displays a shortened form for known users with pre-filled fields, and a "
            "standard form for net-new visitors, using Adobe Target for audience "
            "targeting and Arc Design System for all UI components"
        ),
        "expected_min_score": 65,
        "section_answers": {

            "Strategy & Purpose": """\
The progressive profiling form component solves the problem of over-asking known visitors
for data they have already provided, which causes form abandonment and reduces lead data
quality. By displaying only 2–3 new fields to known users (with existing data pre-filled
or hidden), we reduce friction and improve completion rates while continuing to enrich
lead profiles in Marketo over time.

Team: Gryffindors (design + implementation), Richard (PM).

Business goals supported:
- Increase form completion rates for known users
- Improve lead data quality in Marketo through progressive data collection
- Reduce form abandonment on product pages, events pages, and resource downloads

Reusability: the component is designed for deployment across multiple page types —
events pages, product pages, resource downloads. Configuration managed through AEM
(field selection, progressive rules) — no engineering deployment required for new
form instances.

Target audience: web visitors on servicenow.com — both known users (identified via
Tealium CDP) and net-new visitors.

Expected user interaction: net-new visitors see the full standard form. Known users
see a shorter form with only 2–3 new fields; existing data is pre-filled or hidden.
Tealium CDP unavailability triggers a fallback to the full standard form.

[NEEDS INPUT: Feature owner title, PM name confirmation, tech lead name]
[NEEDS INPUT: Quantitative KPI targets (completion rate improvement targets, etc.)]
[NEEDS INPUT: Parent Epic link]
""",

            "Design & User Experience": """\
Design system: Arc Design System components only — no custom styling permitted.
WCAG 2.2 AA compliance required across all states.
Responsive: desktop, tablet, and mobile.

Component states (all must be supported):
1. Default (net-new): all fields visible, standard labels, full form layout
2. Known user: reduced field set (2–3 new fields), pre-filled values shown as
   editable, hidden fields not shown
3. Loading: skeleton state while Tealium CDP resolves visitor identity (<200ms target)
4. Error/fallback: full standard form displayed, no error messaging shown to user
5. Validation error: inline field-level errors per Arc Design System error patterns
6. Submission success: confirmation state, no page reload

Responsive behavior:
- Desktop, tablet, and mobile — use Arc grid and breakpoints throughout
- No fixed-width constraints — component adapts to host page layout

Accessibility-specific design requirements:
- ARIA live regions required for dynamic field show/hide
- Focus management: when fields are hidden for known users, focus must not be
  trapped or skip unexpectedly; focus moves to next visible field
- Keyboard navigable, screen reader compatible throughout all states
- 44px minimum touch targets on mobile (Arc standard)

Animations: TBD with design team. If field show/hide animation used, must respect
prefers-reduced-motion media query.

[NEEDS INPUT: Wireframes or mockup links (if available)]
[NEEDS INPUT: Confirmed animation approach from design review]
""",

            "Content & Localization": """\
Content management: all form configuration managed through AEM — field list, progressive
rules, fallback behavior, success redirect URL, and Marketo form ID. No engineering
deployment required to create new form instances or update configuration.

Field labels and copy follow existing ServiceNow.com form vocabulary. Error messages
use Arc Design System error pattern library (specific, actionable, non-blaming).

Fallback behavior: if Tealium CDP is unavailable, the component displays the full
standard form. No error message is shown to the visitor.

No localization requirements identified for V1. US-first launch.

[NEEDS INPUT: Localization strategy for subsequent geo rollouts]
[NEEDS INPUT: Consent language copy — legal review required before launch]
[NEEDS INPUT: Specific field label vocabulary confirmation from design/content team]
""",

            "SEO & Analytics": """\
SEO: this is a UI component — not a page. The component itself is not indexed by search
engines. Pages hosting the component manage their own SEO independently. No component-level
SEO requirements.

Analytics events (all fired via Tealium CDP):
- form_load (with user_type: known | net-new)
- form_field_focus (field_name)
- form_submission_success (fields_submitted, user_type)
- form_submission_failure (error_type)
- form_abandoned (last_field_interacted)
- progressive_fields_hidden (count_hidden)
- fallback_triggered (reason: tealium_unavailable | timeout)

[NEEDS INPUT: Full event schema including all properties per event (page_context, form_id, etc.)]
[NEEDS INPUT: KPI dashboard location (Tableau instance, dashboard name)]
[NEEDS INPUT: GDPR/CCPA privacy review status for analytics event schema]
""",

            "Engineering & Technical Requirements": """\
Tech stack dependencies:
- Adobe Target: delivers component variant based on audience segment
  (known user vs. net-new) via mbox call on component load
- Tealium CDP: visitor identity resolution, event forwarding for analytics
  — uses utag.js client-side tag and Tealium data layer object
- AEM: form configuration and component registration; self-service authoring
- Arc Design System: all UI primitives, no custom styling
- Marketo: downstream lead capture — form submits to Marketo

No custom backend API — all integrations are client-side.

Configuration props the component must accept:
- field_list: ordered list of fields to display
- progressive_rules: field visibility rules for known users
- fallback_behavior: behavior when Tealium CDP is unavailable
- success_redirect_url: post-submission redirect (optional)
- marketo_form_id: target Marketo form for submission
- adobe_target_mbox: mbox name for audience targeting

Performance: component load + identity resolution must complete in <200ms.

[NEEDS INPUT: AEM component architecture (AEM Core Components vs. SPA framework)]
[NEEDS INPUT: Versioning strategy for component library updates]
[NEEDS INPUT: Marketo field name mappings for each form field]
""",

            "Accessibility & Compliance": """\
WCAG 2.2 AA compliance required — full audit before launch (Gryffindors team).

Accessibility requirements:
- Keyboard navigation: logical tab order across all component states, no keyboard traps
- Screen reader: all fields, labels, errors, and state changes announced correctly
- ARIA live regions: required for dynamic field show/hide when known-user state renders
- Focus management: when fields are hidden for known users, focus moves to next visible
  field without skipping or trapping
- Color contrast: all text meets 4.5:1 ratio per WCAG 2.2
- Touch targets: 44px minimum on mobile per Arc Design System standards

Compliance:
- GDPR/CCPA: consent language must be reviewed and approved by legal and privacy teams
  before launch. Form submits to Marketo — data retention and processing policies must
  be disclosed in form consent language.
- Legal review required for all data capture fields.

Approval workflow: Legal review (consent language) → Privacy team sign-off →
Design lead approval (labels/copy) → PM sign-off → QA validation → launch.
""",

            "Testing & QA": """\
QA owner: Gryffindors team. WCAG 2.2 full accessibility audit required before launch.

QA scope:
- Functional: all 6 component states tested (default, known user, loading,
  error/fallback, validation error, submission success)
- Accessibility: WCAG 2.2 AA audit — keyboard navigation, screen reader,
  ARIA live regions, focus management, color contrast
- Cross-browser: Chrome, Firefox, Safari, Edge
- Responsive: desktop (1440px), tablet (768px), mobile (375px)
- Analytics: verify all 7 Tealium events fire with correct schema on all states
- Performance: component load + identity resolution <200ms on 4G connection

Legal review: consent language must be approved by legal and privacy teams before
QA sign-off and launch.

Open questions requiring test case definition:
- Tealium CDP unavailability scenario (confirm fallback to full form)
- Maximum fields per session for known users (2 or 3 — TBD)
- Animation behavior under prefers-reduced-motion (TBD with design)
""",

            "Publishing & Release Management": """\
Timeline: Q2 PI (PI 26.2). No hard content freeze confirmed.

Deployment path:
1. Development (AEM + Adobe Target configured for known/net-new audiences)
2. Staging — QA validation (functional + accessibility + analytics)
3. Legal/privacy review of consent language
4. Production deployment
5. Soft launch on one page, monitor metrics, expand to additional pages

Feature flag: required — enables controlled rollout and instant rollback
if component issues are detected post-launch.

Geo rollout: US first. Localization requirements TBD for subsequent markets.

Post-launch:
- Gryffindors team maintains component
- AEM authoring guide required for marketing teams deploying the form on new pages

[NEEDS INPUT: Sprint milestone breakdown with target dates]
[NEEDS INPUT: Confirmed feature flag implementation approach]
""",
        },
    },

    {
        "id": "exp_001_boosted",
        "name": "Progressive Profiling Form Component (boosted)",
        "feature_type": "EXPERIENCE",
        "description": (
            "Build a progressive profiling form component for servicenow.com that "
            "displays a shortened form for known users with pre-filled fields, and a "
            "standard form for net-new visitors, using Adobe Target for audience "
            "targeting and Arc Design System for all UI components"
        ),
        "expected_min_score": 80,
        "section_answers": {

            "Strategy & Purpose": """\
The progressive profiling form component solves the problem of over-asking known visitors
for data they have already provided, reducing form abandonment and improving lead data
quality. Known users see only 2–3 new fields; existing data is pre-filled or hidden.

Feature Owner: Richard (Senior PM, Personalization)
Tech Lead: Gryffindors team lead (design + implementation)
Key Reviewers: Design system lead (Arc compliance), Accessibility lead (WCAG 2.2 audit),
QA lead (Gryffindors), Legal (consent language review)

Quantitative targets:
- Component load-to-interaction time: <200ms for identity resolution + field rendering
- Form completion rate for known users: target 40% improvement vs. full form baseline
- Form abandonment rate: target 25% reduction vs. full form baseline
- Accessibility: 0 WCAG 2.2 AA violations at launch (full audit required)

Parent Epic: Buying Group Intelligence — Q2 PI (PI 26.2) delivery.
Strategic fit: the progressive profiling form is the user-facing data collection surface
for the Buying Group Intelligence strategy. Without this component, the classification
engine (separate CAPABILITY feature) has no primary data collection mechanism.

Reusability: component deployable across events pages, product pages, resource downloads.
AEM configuration enables self-service deployment — no engineering required for new instances.

Key messages:
- "Progressive profiling collects richer data over time without overwhelming users"
- "Known users get a personalized, shorter experience — new users get a standard form"
- "Build once, deploy anywhere — AEM configuration enables self-service deployment"
""",

            "Design & User Experience": """\
Design system: Arc Design System — all UI primitives, no custom styling permitted.
Design tokens: use Arc spacing, typography, and color tokens throughout.
WCAG 2.2 AA compliance required across all states.
Responsive: desktop (1440px), tablet (768px), mobile (375px) — Arc grid throughout.

Component states and design specs:
1. Default (net-new): standard Arc form layout, all fields visible
2. Known user: reduced field set, pre-filled fields displayed in read-only style
   per Arc pattern, edit affordance visible
3. Loading: Arc skeleton component for form area (<200ms target)
4. Fallback: identical to Default — no error state visible to user
5. Validation error: Arc inline error pattern, field-level messaging
6. Success: Arc success state, brief confirmation copy, no page reload

Responsive behavior:
- Desktop (1440px): standard form width per Arc grid
- Tablet (768px): full-width form, stacked layout
- Mobile (375px): full-width, touch-friendly field sizing (44px min touch target)

Animations: TBD with design team. If field show/hide animation is used, must be
<300ms and must respect prefers-reduced-motion media query.

Accessibility-specific design:
- ARIA live regions required for dynamic field show/hide
- Focus management: when fields hidden for known users, focus moves to next visible
  field without skipping or trapping
- Keyboard navigable, screen reader compatible throughout all 6 states
""",

            "Content & Localization": """\
Content management: all form configuration managed through AEM via component dialog.
Field selection, progressive rules, fallback behavior, success redirect URL, and
Marketo form ID configured per instance — no engineering deployment for new instances.

Tone and voice: Professional and concise — form labels and help text follow
ServiceNow brand standards. Error messages use Arc Design System error pattern library
(specific, actionable, non-blaming).

Key copy requirements:
- Field labels: consistent with existing ServiceNow.com form vocabulary
- Error messages: follow Arc Design System error pattern library
- Success confirmation: brief, clear, no page reload required
- Consent language: legal review required before launch for all data capture fields —
  privacy team must approve consent copy

Compliance:
- GDPR/CCPA: consent language reviewed and approved by legal and privacy teams
- Data capture: form submits to Marketo — data retention and processing policies
  documented and disclosed in form consent language
- WCAG 2.2 AA: all copy meets readability and contrast requirements

Approval workflow: Legal review (consent language) → Privacy team sign-off →
Design lead approval (copy/labels) → PM sign-off → QA validation → launch

No V1 localization requirements. US-first launch. International localization TBD.
""",

            "SEO & Analytics": """\
SEO: this is a UI component, not a page. The component itself is not indexed.
Pages hosting the component manage their own SEO independently — no component-level
SEO requirements. The component supports host page SEO via correct ARIA attributes
and semantic HTML (Arc Design System standard).

Analytics events (all fired via Tealium CDP):
- form_load: {user_type: "known" | "net-new", page_context, form_id}
- form_field_focus: {field_name, user_type, form_id}
- form_submission_success: {fields_submitted: count, user_type, form_id}
- form_submission_failure: {error_type, user_type, form_id}
- form_abandoned: {last_field_interacted, user_type, form_id}
- progressive_fields_hidden: {count_hidden, user_type, form_id}
- fallback_triggered: {reason: "tealium_unavailable" | "timeout", form_id}

KPI tracking (Tealium → Tableau):
- Form completion rate by user type (known vs. net-new)
- Field-level abandonment rate — identify which fields cause drop-off
- Fallback trigger rate — monitor Tealium CDP availability impact
- Time to complete form — known vs. net-new comparison
- 90-day post-launch: known user completion rate vs. pre-launch baseline

Privacy: event schema captures no PII — user_type is derived from Tealium identity,
not stored with the event. Compliant with existing CDP consent framework.
GDPR/CCPA: no additional requirements beyond existing Tealium consent framework.
""",

            "Engineering & Technical Requirements": """\
Component architecture:
- Framework: AEM Core Components (server-side rendered) with client-side JavaScript
  for progressive behavior (field show/hide, pre-fill, validation)
- Registered in AEM component library: /apps/servicenow/components/progressive-form
- No separate SPA framework (React/Angular) — uses Arc Design System vanilla JS patterns
- Standalone AEM component (not a micro-frontend)

API endpoints and integrations (all client-side — no custom backend API):
- Tealium CDP: utag.js client-side tag — identity resolution via visitor profile lookup
  using Tealium's data layer object (no direct API call)
- Adobe Target: at.js mbox call to deliver audience-specific component variant.
  mbox name configured per form instance in AEM.
- Marketo: form submission via Marketo Forms 2.0 API (client-side embed).
  Marketo form ID configured per instance in AEM.

Sprint milestones:
- Sprint 1 (Weeks 1–2): component scaffold + default (net-new) state + AEM registration
- Sprint 2 (Weeks 3–4): known-user variant + Tealium identity integration + Adobe Target
- Sprint 3 (Weeks 5–6): Marketo submission + validation states + error handling
- Sprint 4 (Weeks 7–8): accessibility audit + QA + performance optimization
- Sprint 5 (Week 9): legal/privacy review + soft launch on one page
- Sprint 6 (Week 10): expand to additional pages based on monitoring
Target PI: Q2 PI (PI 26.2)

Versioning: semantic versioning (major.minor.patch) in AEM component library.
Major: breaking changes to configuration schema.
Minor: new features (new field types, new states).
Patch: bug fixes, accessibility improvements.
AEM dialog versioning ensures backward compatibility with existing form instances.

Content model — AEM component configuration:
| Property                            | Type          | Validation              | Marketo Mapping   | Notes                        |
|-------------------------------------|---------------|-------------------------|-------------------|------------------------------|
| form_id                             | string        | required, unique        | —                 | Unique identifier per instance |
| field_list                          | array[object] | min 1 field             | field.marketo_name | Ordered field definitions   |
| field_list[].name                   | string        | required                | maps to Marketo field | Internal field identifier |
| field_list[].label                  | string        | required                | —                 | Display label (translatable) |
| field_list[].type                   | enum          | text,email,phone,select,checkbox | —    | Arc DS field types only      |
| field_list[].required               | boolean       | —                       | —                 | Field-level validation       |
| field_list[].marketo_name           | string        | required                | direct mapping    | Marketo form field name      |
| progressive_rules                   | object        | required                | —                 | Visibility rules for known users |
| progressive_rules.hidden_fields     | array[string] | —                       | —                 | Fields hidden for known users |
| progressive_rules.prefill_source    | enum          | tealium,marketo         | —                 | Data source for pre-fill     |
| fallback_behavior                   | enum          | full_form,partial_form  | required          | Behavior when CDP unavailable |
| success_redirect_url                | URL           | optional, valid URL     | —                 | Post-submission redirect     |
| marketo_form_id                     | string        | required                | —                 | Target Marketo form          |
| adobe_target_mbox                   | string        | required                | —                 | mbox name for targeting      |

Performance: component load + identity resolution <200ms on 4G connection.
""",

            "Accessibility & Compliance": """\
WCAG 2.2 AA compliance required — full audit before launch.

Accessibility requirements:
- Keyboard navigation: logical tab order across all 6 states, no keyboard traps
- Screen reader: all fields, labels, errors, and dynamic state changes announced
- ARIA live regions: required for dynamic field show/hide in known-user state
- Focus management: when fields hidden for known users, focus moves to next visible
  field without skipping or trapping
- Color contrast: all text meets 4.5:1 ratio per WCAG 2.2
- Touch targets: 44px minimum on mobile per Arc Design System standards

Compliance:
- GDPR/CCPA: consent language reviewed and approved by legal and privacy teams.
  Form submits to Marketo — data retention and processing policies documented and
  disclosed in form consent language. No PII captured in analytics event schema.
- Legal review: required for all data capture fields before launch

Approval workflow: Legal review (consent language) → Privacy team sign-off →
Design lead approval → PM sign-off → QA accessibility audit → launch
""",

            "Testing & QA": """\
QA owner: Gryffindors team. WCAG 2.2 full accessibility audit required before launch.

QA scope:
- Functional: all 6 component states tested (default, known user, loading,
  error/fallback, validation error, submission success)
- Accessibility: WCAG 2.2 AA audit — keyboard navigation, screen reader,
  ARIA live regions, focus management, color contrast (all 6 states)
- Cross-browser: Chrome, Firefox, Safari, Edge (all 6 states)
- Responsive: desktop (1440px), tablet (768px), mobile (375px)
- Analytics: verify all 7 Tealium events fire with correct property schema
- Performance: component load + identity resolution <200ms on 4G connection
- Marketo: confirm form submission routes correctly per marketo_form_id configuration
- AEM authoring: confirm configuration props render correctly per component dialog

Legal/privacy review of consent language required before QA sign-off and launch.

Edge cases:
- Tealium CDP unavailable: full form renders, no error visible to user
- Adobe Target timeout: fallback to net-new (full form) state
- All fields hidden for known user (edge config): at minimum one field must show
- Prefers-reduced-motion: no animations, instant field transitions
""",

            "Publishing & Release Management": """\
Timeline: Q2 PI (PI 26.2). No hard content freeze confirmed.

Sprint milestones:
- Sprint 1 (Weeks 1–2): component scaffold + default state + AEM registration
- Sprint 2 (Weeks 3–4): known-user variant + Tealium + Adobe Target integration
- Sprint 3 (Weeks 5–6): Marketo submission + validation + error handling
- Sprint 4 (Weeks 7–8): accessibility audit + QA + performance
- Sprint 5 (Week 9): legal/privacy review + soft launch on one page
- Sprint 6 (Week 10): expand rollout based on monitoring

Deployment path:
1. Development (AEM + Adobe Target staging)
2. QA: functional + accessibility + analytics verification
3. Legal/privacy review of consent language
4. Production deployment
5. Soft launch on one page, monitor KPIs (completion rate, fallback rate)
6. Expand to additional pages in Sprint 6

Feature flag: required — enables controlled rollout and instant rollback.
Rollback: disable feature flag; component reverts to existing non-progressive form.

Geo rollout: US first. Localization requirements TBD for subsequent markets.

Post-launch:
- Gryffindors team maintains component
- AEM authoring guide required for marketing teams before soft launch
- Semantic versioning enforced for all component library updates
""",
        },
    },
]
