# Boost Inputs — Case 1: CAPABILITY
## Buying Group Identification

Use these in the **💡 Boost your score before improving** section of the Review stage.
Paste each block into the corresponding input field.

---

## Feature Definition & Objective
*Paste when this section scores below 75%*

```
Feature Owner: Richard (Senior PM, Personalization)
Tech Lead: TBD — Personalization pod owns implementation
Key Reviewers: Personalization pod leads, Marketing Ops, Sales Ops
Quantitative target: Improve TAL account coverage from baseline to 80% classified
within 90 days of launch. Reduce unclassified visitor rate on TAL accounts by 50%.
Parent Epic: Buying Group Intelligence — Q3 strategic initiative to improve
account-based personalization across servicenow.com.
```

---

## Content Strategy & Value Proposition
*Paste when this section scores below 75%*

```
KPI targets:
- 80% of TAL account visitors classified into at least one buying group role
  within 90 days of launch
- Confidence score threshold of 60+ required for content targeting activation
- Reduce "unknown visitor" rate on TAL accounts from current baseline by 50%
- Measure: Adobe Target A/B test showing role-targeted content vs. generic
  content — target 15% improvement in engagement metrics (time on page, CTA clicks)

Parent Epic: Buying Group Intelligence — part of Q3 Account-Based Experience
initiative. Links to ServiceNow's TAL strategy for 48,000 priority accounts.
Strategic fit: Enables downstream personalization for Champion, Economic Buyer,
Influencer, User, and Ratifier roles — directly supports pipeline acceleration goals.
```

---

## Copywriting, Messaging & Compliance
*Paste when this section scores below 75%*

```
Tone and voice: Professional and data-driven — consistent with ServiceNow brand
standards. Avoid jargon; write for cross-functional audiences including engineering,
marketing, and sales ops.

Key messages for documentation and UI copy:
- "Classify every visitor. Target every role." — primary value prop
- Classification is based on behavioral signals only — no PII stored in the
  classification engine
- Confidence scores (0-100) power personalization — only activate targeting
  above 60+ threshold

Legal and compliance:
- GDPR/CCPA review required before launch — classification engine processes
  behavioral data; confirm with legal that consent framework covers this use case
- Privacy team must sign off on data retention policy for classification profiles
- No personally identifiable information stored in the classification engine itself —
  only behavioral signal aggregates and confidence scores

Approval workflow: Legal review → Privacy team sign-off → PM approval → launch
```

---

## SEO, SEM, Analytics
*Paste when this section scores below 75%*

```
This is a backend Capability — not a user-facing page. SEO indexing not applicable.
Analytics tracking requirements:
- Tealium CDP: fire classification events when role confidence score is assigned
- Event schema: visitor_classified {role, confidence_score, account_id, is_TAL}
- Adobe Target: use classification as audience segment for content targeting
- Marketo: enrich lead records with highest-confidence role classification
- KPI dashboard: Tableau (existing) — add Buying Group Classification view
- UTM parameters: capture referral source as classification signal
- GDPR/CCPA: classification based on behavioral signals only, no PII stored
  in classification engine — compliant with existing CDP consent framework
```

---

## Campaigns
*Paste when this section scores below 75%*

```
This is a Capability feature — not a campaign landing page. Direct campaign
dependencies:
- Adobe Target campaigns will consume the role classification as audience input
- Personalization campaigns targeting Economic Buyers, Champions, and Influencers
  will activate once classification confidence threshold (60+) is met
- No paid campaign integration in V1 — classification feeds organic and
  personalization campaigns only
- Email: Marketo lead enrichment with role classification will improve
  email segmentation accuracy for nurture programs
- Measure: Track downstream campaign engagement lift segmented by classified
  vs. unclassified visitors (90-day post-launch measurement window)
```

---

## Engineering, Publishing, QA & Content Model
*Paste when this section scores below 75%*

```
Timeline: Q3 PI target — no hard deadline confirmed. Real-time classification
preferred over 24-hour batch for Adobe Target use case (decision pending).
QA: No QA team assigned yet — Personalization pod to identify QA owner.
Acceptance criteria: Classification confidence scores must be reproducible
within ±5 points across identical signal sets.
Content model — classification output schema:
| Field | Type | Source | Destination |
|---|---|---|---|
| visitor_id | string | Tealium CDP | All systems |
| account_id | string | TAL lookup | Marketo, Target |
| is_TAL | boolean | TAL lookup | Target audiences |
| role_champion | integer 0-100 | Signal engine | Tealium, Target |
| role_economic_buyer | integer 0-100 | Signal engine | Tealium, Target |
| role_influencer | integer 0-100 | Signal engine | Tealium, Target |
| role_user | integer 0-100 | Signal engine | Tealium, Target |
| role_ratifier | integer 0-100 | Signal engine | Tealium, Target |
| primary_role | string | Derived | Marketo enrichment |
| classification_timestamp | datetime | System | All systems |
Post-launch: Monitor classification accuracy monthly. Retrain signal weights
quarterly based on Marketo lead-to-opportunity conversion data.
```

---

## Studio, Design & Accessibility
*Paste when this section scores below 75%*

```
This is a backend Capability — no UI components or design requirements.
The classification engine operates headlessly. All output surfaces through
Adobe Target (content delivery), Tealium CDP (event forwarding), and
Marketo (lead record enrichment). No user-facing design work required.
Performance target: classification must complete within 200ms to support
real-time Adobe Target audience evaluation.
Taxonomy: classify as capability/personalization/buying-group in AEM taxonomy.
```

---

## Notes on Usage

- **Case 1 typically scores 87/100 without boost inputs** — the notes are rich enough
  that most sections score above 75% without help
- Sections most likely to need boost inputs: Feature Definition & Objective
  (missing stakeholder names) and Copywriting/Compliance (missing legal review details)
- SEO/Analytics: this is a backend capability with no page SEO — the boost input
  clarifies that to the Reviewer
- User Stories & Acceptance Criteria has scored consistently 17-18/20 on this case
  — do NOT fill in boost inputs for that section, it doesn't need help
- With the Opus-redesigned Improver (v2), Case 1 target is 90+ without boost inputs
