# Test Case 1: CAPABILITY
## Buying Group Identification

---

### Describe your feature

```
Build a buying group identification capability that classifies web visitors into buying group roles (Champion, Economic Buyer, Influencer, User, Ratifier) based on their behavioral signals on servicenow.com
```

---

### Paste your notes

```
Project: Buying Group Intelligence
Goal: Classify anonymous and known web visitors into buying group roles using behavioral signals so we can serve role-appropriate content and personalization experiences.

Buying group roles we need to detect:
- Champion: high engagement, multiple visits, deep product page exploration
- Economic Buyer: pricing page visits, ROI content, executive-level job title signals
- Influencer: whitepaper downloads, comparison content, peer review site referrals
- User: product documentation, how-to content, support pages
- Ratifier: compliance/security content, legal pages, low visit frequency but high intent signals

Signal sources:
- Page visit history (via Tealium CDP)
- Content category interactions (tagged in AEM)
- Job title from Marketo lead record (for known users)
- Referral source and UTM parameters
- Form submission history

Tech stack:
- Tealium CDP: event collection and identity stitching
- Adobe Target: deliver role-specific content variants
- Marketo: lead record enrichment with role classification
- AEM: content tagging by buying group role
- ServiceNow TAL (Target Account List): 48,000 accounts

The classification should produce a confidence score (0-100) per role, not just a binary assignment. A visitor can have scores across multiple roles — we surface the highest confidence role for targeting.

Target accounts from TAL get priority scoring. Unknown visitors from non-TAL companies get a lighter classification pass.

Team: Personalization pod owns this. No QA team assigned yet.
Timeline: Q3 PI target. No hard deadline confirmed.
Open: Do we need real-time classification or can we batch update Tealium profiles every 24 hours? Leaning toward real-time for Adobe Target use case.
```

---

### Expected routing
`CAPABILITY`

### Baseline scores (no boost input)
- Original: ~71/100
- Sections reliably above 75%: Scope, User Stories & Acceptance Criteria
- Sections reliably below 75%: SEO/SEM/Analytics, Campaigns, Copywriting, Feature Definition & Objective

### Notes
- Notes are strong on technical architecture and system integration
- Weak on: stakeholder names, quantitative KPIs, campaign plans, SEO keywords
- Filling the boost inputs for "Feature Definition & Objective" and "Content Strategy & Value Proposition" in the Review stage should push score to 85+
