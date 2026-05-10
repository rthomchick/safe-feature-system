# Test Case 3: EXPERIENCE
## Progressive Profiling Form Component

---

### Describe your feature

```
Build a progressive profiling form component for servicenow.com that displays
a shortened form for known users with pre-filled fields, and a standard form
for net-new visitors, using Adobe Target for audience targeting and Arc Design
System for all UI components
```

---

### Paste your notes

```
Project: Progressive Profiling Form — UI Component
Team: Gryffindors (design + implementation), Richard (PM)

Component overview:
The progressive profiling form is a reusable UI component that adapts its
field display based on visitor identity. It is NOT the data collection engine
(that's a separate Capability feature) — this is the form UI component itself.

Component behavior:
- Known users: form displays 2-3 new fields only; existing data pre-filled or hidden
- Net-new visitors: full standard form displayed
- If Tealium CDP is unavailable: fallback to full standard form (no error shown to user)
- Field hiding/pre-filling is driven by Tealium CDP identity resolution passed
  via Adobe Target audience segments

States the component must support:
- Default (net-new): all fields visible, standard labels
- Known user: reduced field set, pre-filled values editable
- Loading: skeleton state while Tealium identity resolves (target: <200ms)
- Error/fallback: full form displayed, no error messaging shown to user
- Validation error: inline field-level errors per Arc Design System patterns
- Submission success: confirmation state, no page reload

Design requirements:
- Arc Design System components only — no custom styling
- WCAG 2.2 AA compliance required
- Responsive: desktop, tablet, mobile
- Keyboard navigable, screen reader compatible
- ARIA live regions required for dynamic field show/hide
- Focus management: when fields are hidden for known users, focus must not
  be trapped or skip unexpectedly

Reusability requirements:
- Must be deployable across events pages, product pages, resource downloads
- Configuration managed through AEM (field selection, progressive rules)
  — no engineering deployment required for new form instances
- Component must accept configuration props: field list, progressive rules,
  fallback behavior, success redirect URL

Analytics events to fire:
- form_load (with user_type: known | net-new)
- form_field_focus (field_name)
- form_submission_success (fields_submitted, user_type)
- form_submission_failure (error_type)
- form_abandoned (last_field_interacted)
- progressive_fields_hidden (count_hidden)
- fallback_triggered (reason: tealium_unavailable | timeout)

Tech dependencies:
- Adobe Target: delivers component variant (known vs net-new audience)
- Tealium CDP: identity resolution, event forwarding
- AEM: form configuration and component registration
- Arc Design System: all UI primitives
- Marketo: downstream lead capture (form submits to Marketo)

Timeline: Q2 PI (PI 26.2). No hard content freeze identified.
QA: Gryffindors team. WCAG 2.2 audit required before launch.

Open questions:
- Maximum fields per session for known users: 2 or 3? Leaning toward 2-3 configurable.
- Do we need an animation/transition when fields are hidden? TBD with design.
- Legal review required for data capture consent language on form.
```

---

### Expected routing
`EXPERIENCE`

### Why this is EXPERIENCE not CAPABILITY
The buying group classification capability (Case 1) is the backend engine.
This is the form UI component — defined by its visual states, responsive behavior,
interaction patterns, and component architecture. The primary deliverable is
how the component looks, behaves, and responds across states. That's EXPERIENCE.

### Expected baseline scores
- Strong sections: Strategy & Purpose (notes are clear), Design & UX (states well defined),
  Engineering (tech stack named), Accessibility (WCAG explicitly called out)
- Weaker sections: SEO/Analytics (component, not page), Campaigns (no campaign info),
  Copywriting (no copy guidance in notes)
- User Stories: should score well — notes contain specific personas and behaviors

### Notes on this test case
- This is the hardest routing case to get right — it describes the same
  product area as Case 1 (Capability) but from the UI component perspective
- The Router should classify as EXPERIENCE because the notes emphasize
  component states, Arc Design System, and visual behavior
- If the Router misclassifies as CAPABILITY, use the override dropdown
  to correct it before proceeding
