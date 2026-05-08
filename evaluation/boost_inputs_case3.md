# Boost Inputs — Case 3: EXPERIENCE
## Progressive Profiling Form Component

Use these in the **💡 Boost your score before improving** section of the Review stage.
Paste each block into the corresponding input field.

---

## Feature Definition & Objective
*Paste when this section scores below 75%*

```
Feature Owner: Richard (Senior PM, Personalization)
Tech Lead: Gryffindors team lead (design + implementation)
Key Reviewers: Design system lead (Arc compliance), Accessibility lead (WCAG 2.2),
QA lead (Gryffindors), Legal (consent language review)
Quantitative targets:
- Component load-to-interaction time: <200ms for identity resolution + field rendering
- Form completion rate for known users: target 40% improvement vs. full form baseline
- Form abandonment rate: target 25% reduction vs. full form baseline
- Accessibility: 0 WCAG 2.2 AA violations at launch (full audit required)
Parent Epic: Buying Group Intelligence — Q2 PI (PI 26.2) delivery.
Strategic fit: The progressive profiling form component is the user-facing delivery
mechanism for the buying group data enrichment strategy. Without this component,
the Capability (classification engine) has no data collection surface.
```

---

## Content Strategy & Value Proposition
*Paste when this section scores below 75%*

```
Primary value proposition: Known users experience significantly less friction —
seeing only 2-3 new fields instead of a full form — which increases completion
rates and improves lead data quality in Marketo.

Key messages (for documentation and internal stakeholders):
- "Progressive profiling collects richer data over time without overwhelming users"
- "Known users get a personalized, shorter experience — new users get a standard form"
- "Build once, deploy anywhere — AEM configuration enables self-service deployment
  across events, product pages, and resource downloads"

CTAs on the form:
- Primary: form submit button (label varies by deployment context)
- Secondary: none — form is purpose-built for data capture, no competing CTAs

Personalization: The component itself IS the personalization experience — the
known-user variant is the personalized state, delivered via Adobe Target.
```

---

## Copywriting, Messaging & Compliance
*Paste when this section scores below 75%*

```
Tone and voice: Professional and concise — form labels and help text follow
ServiceNow brand standards. Error messages use Arc Design System patterns
(specific, actionable, non-blaming).

Key copy requirements:
- Field labels: consistent with existing ServiceNow.com form vocabulary
- Error messages: follow Arc Design System error pattern library
- Success confirmation: brief, clear, no page reload required
- Consent language: legal review required before launch for all data capture
  fields — privacy team must approve consent copy

Compliance:
- GDPR/CCPA: consent language must be reviewed and approved by legal and privacy teams
- Data capture: form submits to Marketo — confirm data retention and processing
  policies are documented and disclosed in form consent language
- WCAG 2.2 AA: all copy must meet readability and contrast requirements

Approval workflow: Legal review (consent language) → Privacy team sign-off →
Design lead approval (copy/labels) → PM sign-off → QA validation → launch
```

---

## SEO, SEM, Analytics
*Paste when this section scores below 75%*

```
SEO: This is a UI component, not a page. The component itself is not indexed.
Pages hosting the component manage their own SEO — no component-level SEO requirements.

Analytics events (all fired via Tealium CDP):
- form_load: {user_type: "known" | "net-new", page_context, form_id}
- form_field_focus: {field_name, user_type, form_id}
- form_submission_success: {fields_submitted: count, user_type, form_id}
- form_submission_failure: {error_type, user_type, form_id}
- form_abandoned: {last_field_interacted, user_type, form_id}
- progressive_fields_hidden: {count_hidden, user_type, form_id}
- fallback_triggered: {reason: "tealium_unavailable" | "timeout", form_id}

KPI tracking:
- Form completion rate by user type (known vs. net-new) — Tealium → Tableau
- Field-level abandonment rate — identify which fields cause drop-off
- Fallback trigger rate — monitor Tealium CDP availability impact
- Time to complete form — known vs. net-new comparison

Privacy: Event schema captures no PII — user_type is derived from Tealium identity,
not stored with the event. Compliant with existing CDP consent framework.
GDPR/CCPA: no additional requirements beyond existing Tealium consent framework.
```

---

## Campaigns
*Paste when this section scores below 75%*

```
This is a UI component — not a campaign landing page. Direct campaign dependencies:

Adobe Target integration:
- Adobe Target delivers the component variant based on audience segment
  (known user vs. net-new) — this IS the campaign delivery mechanism
- A/B testing capability: component architecture supports future A/B tests
  on form field order, field count, and CTA copy (not in V1 scope)

Email campaign dependencies:
- Forms deployed on resource download pages may receive email campaign traffic
- UTM parameters passed through to Marketo on form submission for attribution
- No email campaign changes required for component launch

Paid campaign dependencies:
- Forms on product pages may receive SEM traffic — component must load
  and function correctly for all traffic sources
- No paid campaign-specific configuration required

Measurement:
- Form completion rate as a conversion metric in Tableau
- Attribution via UTM parameters passed to Marketo on submission
- 90-day post-launch comparison: known user completion rate vs. pre-launch baseline
```

---

## Engineering, Publishing, QA & Content Model
*Paste when this section scores below 75%*

```
Timeline: Q2 PI (PI 26.2). No hard content freeze confirmed.
QA: Gryffindors team. WCAG 2.2 full audit required before launch.

Deployment path:
1. Development → Staging (AEM + Adobe Target configured)
2. QA validation (functional + accessibility + analytics)
3. Legal/privacy review of consent language
4. Production deployment
5. Soft launch on one page, monitor, expand to additional pages

Geo rollout: US first. Localization requirements TBD for subsequent markets.

Feature flag: Required — enables controlled rollout and instant rollback
if component issues are detected post-launch.

Content model — AEM component configuration:
| Property | Type | Description | Required |
|---|---|---|---|
| form_id | string | Unique identifier for this form instance | Yes |
| field_list | array | Ordered list of fields to display | Yes |
| progressive_rules | object | Field visibility rules for known users | Yes |
| fallback_behavior | enum | full_form | partial_form | Yes |
| success_redirect_url | URL | Post-submission redirect | No |
| marketo_form_id | string | Target Marketo form for submission | Yes |
| adobe_target_mbox | string | mbox name for audience targeting | Yes |

QA requirements:
- Functional: all 6 component states tested (default, known user, loading,
  error/fallback, validation error, submission success)
- Accessibility: WCAG 2.2 AA audit — keyboard navigation, screen reader,
  ARIA live regions, focus management, color contrast
- Cross-browser: Chrome, Firefox, Safari, Edge
- Responsive: desktop (1440px), tablet (768px), mobile (375px)
- Analytics: verify all 7 Tealium events fire with correct schema
- Performance: component load + identity resolution <200ms on 4G connection

Post-launch ownership: Gryffindors team maintains component.
Documentation: AEM authoring guide required for marketing teams deploying the form.
```

---

## Studio, Design & Accessibility
*Paste when this section scores below 75%*

```
Design system: Arc Design System — all UI primitives, no custom styling permitted.
Design tokens: use Arc spacing, typography, and color tokens throughout.

Component states and design specs:
- Default (net-new): standard Arc form layout, all fields visible
- Known user: reduced field set, pre-filled fields displayed in read-only
  style per Arc pattern, edit affordance visible
- Loading: Arc skeleton component for form area (<200ms target)
- Fallback: identical to Default — no error state visible to user
- Validation error: Arc inline error pattern, field-level messaging
- Success: Arc success state, brief confirmation copy

Responsive behavior:
- Desktop (1440px): standard form width per Arc grid
- Tablet (768px): full-width form, stacked layout
- Mobile (375px): full-width, touch-friendly field sizing (44px min touch target)

Animations: TBD with design team. If field show/hide animation is used,
must be <300ms, respect prefers-reduced-motion media query.

Accessibility requirements:
- WCAG 2.2 AA compliance — full audit before launch
- Keyboard navigation: logical tab order, no keyboard traps
- Screen reader: all fields, labels, errors announced correctly
- ARIA live regions: required for dynamic field show/hide
- Focus management: when fields hidden for known users, focus moves to
  next visible field without skipping or trapping
- Color contrast: all text meets 4.5:1 ratio per WCAG 2.2

Performance:
- Component load time: <200ms for identity resolution + initial render
- Core Web Vitals: no negative impact on hosting page LCP or CLS
- Taxonomy: classify as component/personalization/form in AEM component library
```

---

## Notes on Usage

- **Case 3 is the Experience archetype** — component states, Arc Design System,
  ARIA requirements. These notes are richer than typical PM notes, so expect
  a higher baseline score than Case 2 (Webpage).
- **Most likely to need boost inputs:** SEO/Analytics (component, not page —
  explain this to the Reviewer), Campaigns (component, not campaign page),
  Copywriting (consent language and error copy requirements)
- **Sections likely to score well without boost:** Strategy & Purpose, Design & UX
  (states well defined in notes), Engineering (tech stack clear), Accessibility,
  User Stories
- **Router note:** This should classify as EXPERIENCE. If it routes to CAPABILITY,
  use the override dropdown — the notes clearly emphasize component states and
  Arc Design System, not the backend classification engine.
- **Target:** 90+ with boost inputs. The notes are strong enough that you may
  reach 85+ without any boost inputs.
