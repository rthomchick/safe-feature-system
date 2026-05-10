# Test Case 2: WEBPAGE
## Financial Services Solutions Page

---

### Describe your feature

```
Create a new solution page for the financial services vertical on servicenow.com targeting Economic Buyers and Champions at banks and insurance companies
```

---

### Paste your notes

```
Page: Financial Services Solutions page
URL target: servicenow.com/solutions/financial-services (new page)

Business objective: Financial services is a priority vertical for Q3. We need a dedicated landing page that speaks to FS-specific pain points and maps to our solutions. Currently we send FS prospects to the generic solutions page — conversion is below average for this segment.

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
- Secondary: "See the ROI Calculator" (links to existing ROI tool)
- Tertiary: "Download the FS Reference Architecture" (gated asset)

SEO targets: "financial services IT service management", "bank digital transformation platform", "insurance workflow automation"

Design: Use existing solutions page template. Hero with FS imagery. 3-column value prop section. Customer logo bar (we have 6 approved FS logos). 1 customer quote (Zurich Insurance approved).

Existing assets available: FS solution brief (PDF), Zurich Insurance case study, ROI calculator (already live).

Dependencies: FS sales team needs to approve messaging. Legal review required for compliance claims. Brand team to source hero imagery.

Timeline: Must be live before Sibos conference (October). Content freeze 2 weeks prior.
Geo rollout: US first, then UK and APAC in follow-on sprint.
QA: Standard QA process — Gryffindors team.
```

---

### Expected routing
`WEBPAGE`

### Baseline scores (no boost input)
- Original: ~62/100
- Sections reliably above 75%: User Stories & Acceptance Criteria
- Sections reliably below 75%: SEO/SEM/Analytics, Campaigns, Copywriting, Feature Definition & Objective, Engineering/Publishing/QA

### Known issue (as of Week 8 Day 5)
The Generator produces a condensed 6-heading spec for Webpage features:
- `## Feature Title`
- `## Description`
- `## Scope (In-Scope)`
- `## Out of Scope`
- `## Solution Approach`
- `## Acceptance Criteria`

Rubric sections like SEO, Campaigns, Copywriting, and Studio/Design have no
corresponding `##` heading. Fix in progress: updating `GENERATOR_SYSTEM_PROMPT`
to require all rubric sections as `##` headings even when notes are thin.

### Notes
- Notes are strong on content strategy, CTAs, SEO keywords, and timeline
- Weak on: stakeholder names, campaign attribution, detailed QA requirements
- Filling "Feature Definition & Objective" boost input with stakeholder names should help significantly
- "Campaigns" boost input should include Sibos campaign tracking requirements
