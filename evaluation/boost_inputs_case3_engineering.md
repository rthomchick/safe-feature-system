# Enriched Engineering Boost Input — Case 3: EXPERIENCE
## Progressive Profiling Form Component

Replace the existing Engineering boost input with this version.
It addresses the specific criteria the Reviewer flagged as missing.

---

## Engineering, Publishing, QA & Content Model
*Paste into the boost input field*

```
Component architecture:
- Framework: AEM Core Components (server-side rendered) with client-side
  JavaScript for progressive behavior (field show/hide, pre-fill, validation)
- Architecture: standalone AEM component — not a micro-frontend. Registered in
  AEM component library under /apps/servicenow/components/progressive-form
- No separate SPA framework (React/Angular) — uses Arc Design System vanilla JS
  patterns for interactive behavior

API endpoints and integrations:
- Tealium CDP: utag.js client-side tag — identity resolution via visitor profile
  lookup (no direct API call; uses Tealium's data layer object)
- Adobe Target: at.js mbox call to deliver audience-specific component variant.
  mbox name configured per form instance in AEM.
- Marketo: form submission via Marketo Forms 2.0 API (client-side embed).
  Marketo form ID configured per instance in AEM.
- No custom backend API — all integrations are client-side

Timeline with milestones:
- Sprint 1 (Weeks 1-2): Component scaffold + default (net-new) state + AEM registration
- Sprint 2 (Weeks 3-4): Known-user variant + Tealium identity integration + Adobe Target
- Sprint 3 (Weeks 5-6): Marketo submission + validation states + error handling
- Sprint 4 (Weeks 7-8): Accessibility audit + QA + performance optimization
- Sprint 5 (Week 9): Legal/privacy review + soft launch on one page
- Sprint 6 (Week 10): Expand to additional pages based on monitoring
Target PI: Q2 PI (PI 26.2)

Versioning strategy:
- Semantic versioning (major.minor.patch) in AEM component library
- Major: breaking changes to configuration schema
- Minor: new features (e.g., new field types)
- Patch: bug fixes, accessibility improvements
- AEM component dialog versioning ensures backward compatibility with existing
  form instances when component is updated

QA: Gryffindors team. WCAG 2.2 full audit required before launch.
QA scope: all 6 component states, keyboard navigation, screen reader,
ARIA live regions, cross-browser (Chrome/Firefox/Safari/Edge),
responsive (1440px/768px/375px), all 7 Tealium events verified

Content model — AEM component configuration:
| Property | Type | Validation | Marketo Mapping | Notes |
|---|---|---|---|---|
| form_id | string | required, unique | — | Unique identifier per instance |
| field_list | array[object] | min 1 field | field.marketo_name | Ordered field definitions |
| field_list[].name | string | required | maps to Marketo field | Internal field identifier |
| field_list[].label | string | required | — | Display label (translatable) |
| field_list[].type | enum | text,email,phone,select,checkbox | — | Arc DS field types only |
| field_list[].required | boolean | — | — | Field-level validation |
| field_list[].marketo_name | string | required | direct mapping | Marketo form field name |
| progressive_rules | object | required | — | Visibility rules for known users |
| progressive_rules.hidden_fields | array[string] | — | — | Fields hidden for known users |
| progressive_rules.prefill_source | enum | tealium,marketo | — | Data source for pre-fill |
| fallback_behavior | enum | full_form,partial_form | required | Behavior when CDP unavailable |
| success_redirect_url | URL | optional, valid URL | — | Post-submission redirect |
| marketo_form_id | string | required | — | Target Marketo form for submission |
| adobe_target_mbox | string | required | — | mbox name for audience targeting |

Feature flag: Required — enables controlled rollout and instant rollback.
Post-launch: Gryffindors team maintains. AEM authoring guide for marketing teams.
```
