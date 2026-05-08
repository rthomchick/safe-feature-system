# Boost Inputs — Case 2: WEBPAGE
## Financial Services Solutions Page

Use these in the **💡 Boost your score before improving** section of the Review stage.
Paste each block into the corresponding input field.

---

## Feature Definition & Objective
*Paste when this section scores below 75%*

```
Feature Owner: Richard (Senior PM, Web Experience)
Tech Lead: TBD — Web Engineering team
Key Reviewers: FS Sales team lead (messaging approval), Legal (compliance claims),
Brand team (hero imagery), Gryffindors QA lead
Quantitative target: Improve FS segment conversion rate from current below-average
baseline to industry benchmark (target: 3-5% CTA form conversion rate).
Measure MQL volume attributable to this page within 90 days of launch.
Parent Epic: Financial Services Vertical Expansion — Q3 priority initiative.
Strategic fit: Dedicated FS page eliminates generic solutions page fallback for
8 of the top 10 global bank prospects — directly supports Q3 pipeline targets.
```

---

## Content Strategy & Value Proposition
*Paste when this section scores below 75%*

```
KPI targets:
- Primary CTA ("Talk to a Financial Services Expert") form conversion: 3-5%
- MQL volume from page: establish 90-day baseline, target 20% above generic page
- Bounce rate: target below 50% (vs. generic solutions page benchmark)
- Time on page: target 2:30+ average
- Pipeline influenced: track Salesforce opportunities with this page in the journey

Value proposition: ServiceNow reduces operational risk and improves compliance
readiness for regulated industries. Proven at 8 of the top 10 global banks.
FFIEC, SOC2, and ISO 27001 compliance support built in.

CTAs in priority order:
1. "Talk to a Financial Services Expert" — form, routes to FS sales team (P0)
2. "See the ROI Calculator" — links to existing live tool (P1)
3. "Download the FS Reference Architecture" — gated PDF asset (P2)
```

---

## Studio, Design & Accessibility
*Paste when this section scores below 75%*

```
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
Taxonomy: tag as solutions/financial-services in AEM taxonomy system.
No custom animations or interactive elements beyond existing template components.
```

---

## SEO, SEM, Analytics
*Paste when this section scores below 75%*

```
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
```

---

## Campaigns
*Paste when this section scores below 75%*

```
Sibos conference campaign (October 2025):
- Page must be live before Sibos — hard deadline drives October content freeze
- All Sibos campaign traffic tagged: utm_campaign=sibos-2025, utm_source per channel
- Paid campaign: ads targeting FS titles (CIO, CTO, COO) at financial institutions
  — landing destination is this page, conversion = primary CTA form submission
- SEM: paid search on target keywords during Sibos conference week

Email campaigns:
- FS nurture track in Marketo: update email CTAs to point to this page
- Post-Sibos follow-up sequence: reference page for "learn more" CTA

Campaign measurement:
- Primary metric: MQL volume attributed to page (Salesforce campaign attribution)
- Secondary metric: CTA form conversion rate by traffic source
- Sibos-specific: pipeline influenced by leads sourced during conference period
- 90-day post-launch report comparing FS page performance vs. generic solutions page
```

---

## Engineering, Publishing, QA & Content Model
*Paste when this section scores below 75%*

```
Timeline:
- Live before Sibos conference (October 2025) — hard deadline
- Content freeze: 2 weeks prior to Sibos
- US launch first, then UK and APAC in follow-on sprint

Geo rollout:
- Phase 1: US (servicenow.com/solutions/financial-services)
- Phase 2: UK (/uk/solutions/financial-services) — hreflang required
- Phase 3: APAC — markets TBD

QA: Gryffindors team — standard QA process
QA scope: layout accuracy, content accuracy, CTA functionality, form routing
to FS sales team, analytics tracking validation, mobile responsiveness

Legal review required: compliance claims (FFIEC, SOC2, ISO 27001 references)
must be approved by legal before launch.

Content model:
| Component | Fields | Type | Notes |
|---|---|---|---|
| Hero | Headline, Subhead, CTA label, CTA URL, Image | AEM component | Brand sources image |
| Value Props | Icon (x3), Title (x3), Body (x3) | AEM component | Existing VP component |
| Logo Bar | Logo image (x6), Alt text (x6) | AEM component | 6 approved logos |
| Customer Quote | Quote text, Attribution, Logo | AEM component | Zurich Insurance |
| Asset Download | Headline, Description, CTA label, Asset URL | Marketo gated form | FS Reference Architecture PDF |
| SEO | Meta title, Meta description, Canonical URL | AEM page properties | |

No new components required — all use existing solutions page template components.
No custom front-end logic or embed code required.
A/B testing: not in V1 — add to V2 roadmap.
```

---

## Notes on Usage

- **Case 2 typically scores 62-72/100 without boost inputs**
- Fill in ALL four fields (Studio, SEO, Campaigns, Engineering) for best results
- With all four boost inputs, best score achieved: **87/100**
- Remaining gap to 90: User Stories & Acceptance Criteria — currently debugging
  a regression issue where this section drops during improvement
- Do NOT fill in boost inputs for sections already above 75% (Feature Definition,
  Content Strategy, Scope, Copywriting) — the Improver doesn't touch those
