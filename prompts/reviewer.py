# prompts/reviewer.py

RUBRIC = {
    "I. Feature Definition & Objective": {
        "max_points": 13,
        "criteria": [
            {"name": "Feature Name", "max": 2, "guidance": "Is the name concise and descriptive enough for all stakeholders to understand at a glance?"},
            {"name": "Objective Thoroughness", "max": 4, "guidance": "Does the objective cover the user, problem, business value, outcome, strategic alignment, and PI-fit?"},
            {"name": "Business/User Context", "max": 2, "guidance": "Is the context user-focused, clear, and relevant to the buyer journey?"},
            {"name": "Clarity & Structure", "max": 2, "guidance": "Is the feature logically organized, clearly written, and free of jargon?"},
            {"name": "Key Stakeholders & Reviewers", "max": 1, "guidance": "Are owners and reviewers listed with clear accountability?"},
            {"name": "Maintenance Ownership", "max": 2, "guidance": "Is ongoing maintenance and ownership defined post-launch?"},
        ],
    },
    "II. Content Strategy & Value Proposition": {
        "max_points": 12,
        "criteria": [
            {"name": "Primary Objective, Key Message, Value Proposition", "max": 3, "guidance": "Is the value prop clear, compelling, and actionable?"},
            {"name": "Problem/Solution Fit", "max": 2, "guidance": "Is the problem clearly stated and the solution directly matched to it?"},
            {"name": "Strategic Fit", "max": 2, "guidance": "Does the value proposition link to broader business or Epic goals?"},
            {"name": "Personalization/Dynamic Content", "max": 2, "guidance": "Is there a plan for personalization or dynamic content experiences?"},
            {"name": "CTAs", "max": 2, "guidance": "Are calls-to-action clear, visible, and contextually relevant?"},
            {"name": "Proof Points", "max": 1, "guidance": "Are testimonials or case studies included where appropriate?"},
        ],
    },
    "III. Scope, Out of Scope, and Dependencies": {
        "max_points": 10,
        "criteria": [
            {"name": "Scope Clarity", "max": 3, "guidance": "Are all in-scope deliverables detailed with clear boundaries?"},
            {"name": "Out of Scope", "max": 2, "guidance": "Are exclusions specific, justified, and sufficient to prevent scope creep?"},
            {"name": "Dependencies", "max": 2, "guidance": "Are internal and external dependencies listed and explained?"},
            {"name": "Alignment & Traceability", "max": 2, "guidance": "Does scope align to stated goals and Epic context?"},
            {"name": "Localization/Translation", "max": 1, "guidance": "Are localization requirements identified and specified?"},
        ],
    },
    "IV. Studio, Design & Accessibility": {
        "max_points": 8,
        "criteria": [
            {"name": "Design Standards", "max": 2, "guidance": "Are design guidelines and templates referenced and applied?"},
            {"name": "Media & Interactivity", "max": 2, "guidance": "Are media types and interactive elements specified?"},
            {"name": "Accessibility", "max": 2, "guidance": "Are WCAG standards and device optimization requirements addressed?"},
            {"name": "Performance, Scalability, Taxonomy", "max": 2, "guidance": "Are performance, scalability expectations, and taxonomy called out?"},
        ],
    },
    "V. Copywriting, Messaging & Compliance": {
        "max_points": 6,
        "criteria": [
            {"name": "Tone & Voice", "max": 1, "guidance": "Is the tone appropriate and consistent with brand standards?"},
            {"name": "Messaging Alignment", "max": 2, "guidance": "Are copy direction, SEO keywords, and messaging guidelines integrated?"},
            {"name": "Legal/Compliance", "max": 1, "guidance": "Is legal, regulatory, or privacy review specified where needed?"},
            {"name": "Localization for Copy", "max": 1, "guidance": "Are content adaptations for regional or global audiences addressed?"},
            {"name": "Approval Workflow", "max": 1, "guidance": "Is the content approval process clearly defined?"},
        ],
    },
    "VI. SEO, SEM, Analytics": {
        "max_points": 12,
        "criteria": [
            {"name": "SEO Strategy", "max": 3, "guidance": "Is there a clear and actionable SEO strategy?"},
            {"name": "SEM", "max": 2, "guidance": "Are paid search and SEM dependencies called out?"},
            {"name": "Keywords & Optimization", "max": 2, "guidance": "Are target keywords specified and justified?"},
            {"name": "Analytics & KPIs", "max": 3, "guidance": "Are KPIs, dashboards, event tracking, and UTM parameters included?"},
            {"name": "Privacy & Compliance", "max": 1, "guidance": "Are GDPR/CCPA and privacy requirements called out?"},
            {"name": "Lifecycle/Redirects", "max": 1, "guidance": "Is there a post-campaign lifecycle plan (redirects, archiving, decommission)?"},
        ],
    },
    "VII. Campaigns": {
        "max_points": 6,
        "criteria": [
            {"name": "Paid Campaigns", "max": 2, "guidance": "Are paid campaign plans and tracking requirements called out?"},
            {"name": "Email Campaigns", "max": 2, "guidance": "Are email campaign dependencies described?"},
            {"name": "Campaign Measurement", "max": 2, "guidance": "Is there a plan for measuring campaign outcomes?"},
        ],
    },
    "VIII. Engineering, Publishing, QA & Content Model": {
        "max_points": 13,
        "criteria": [
            {"name": "Technical Plan & Readiness", "max": 2, "guidance": "Is there a high-level, realistic implementation plan?"},
            {"name": "Systems & Integrations", "max": 2, "guidance": "Are backend dependencies and integrations listed?"},
            {"name": "Timeline, A/B Testing, Versioning", "max": 2, "guidance": "Are timelines, A/B testing requirements, and versioning addressed?"},
            {"name": "QA & Testing", "max": 2, "guidance": "Is QA involvement defined and acceptance criteria testable?"},
            {"name": "Post-Launch Ownership", "max": 1, "guidance": "Is ongoing support and ownership assigned?"},
            {"name": "Content Model Strategy Table", "max": 4, "guidance": "Is a detailed content model table provided?"},
        ],
    },
    "IX. User Stories & Acceptance Criteria": {
        "max_points": 20,
        "criteria": [
            {"name": "INVEST Compliance", "max": 6, "guidance": "Are all user stories INVEST-compliant (Independent, Negotiable, Valuable, Estimable, Small, Testable)?"},
            {"name": "User Story Coverage", "max": 4, "guidance": "Do stories collectively cover the complete feature requirements?"},
            {"name": "Acceptance Criteria Quality", "max": 4, "guidance": "Are acceptance criteria Gherkin-formatted, prioritized using P0-P4, and independently testable?"},
            {"name": "Traceability", "max": 3, "guidance": "Is every user story linked back to a stated feature requirement?"},
            {"name": "Prioritization and Realism", "max": 3, "guidance": "Do priorities reflect real business needs, complexity, and risk?"},
        ],
    },
}

TOTAL_POINTS = sum(s["max_points"] for s in RUBRIC.values())  # Should be 100