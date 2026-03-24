# prompts/experiences.py
from prompts.shared import SAFE_PREAMBLE, SAFE_OUTPUT_FORMAT

TYPE_LABEL = "Experience"
TYPE_EXAMPLE = "Example: Build a filter component, create a tabbed content module, add a sticky nav with scroll-aware behavior."

PREAMBLE = f"{SAFE_PREAMBLE}\n\nExample:\n- Create a new component or new functionality\n\n{SAFE_OUTPUT_FORMAT}"

SECTIONS = {
    "Strategy & Purpose": [
        "What problem does this component solve, and how does it support business goals?",
        "Is this component intended for reuse across multiple pages or is it page-specific?",
        "Who is the target audience, and what is the expected user interaction?",
    ],
    "Design & User Experience": [
        "What design guidelines should this component follow (e.g., branding, accessibility)?",
        "Are there wireframes, mockups, or prototypes available for review?",
        "How does this component behave across different screen sizes (desktop, mobile, tablet)?",
        "What states does this component need to support? (e.g., hover, active, disabled, error)",
        "Does the component require animations or interactive behaviors?",
    ],
    "Content & Localization": [
        "What content will this component display? Is it static, dynamic, or personalized?",
        "Are there any localization or translation requirements?",
        "Will the content be managed through AEM, or is it hardcoded?",
        "Are there fallback states if content is missing or fails to load?",
    ],
    "SEO & Analytics": [
        "Should the component be indexed by search engines?",
        "Are there any structured data requirements (e.g., JSON-LD, Schema.org)?",
        "What KPIs should be tracked for this component? (e.g., clicks, form submissions, interactions)",
        "Do we need event tracking for analytics? If so, what specific events?",
    ],
    "Engineering & Technical Requirements": [
        "What are the technical dependencies for this component? (APIs, services, CMS integration)",
        "Is the component part of a micro-frontend architecture or standalone?",
        "Are there any specific framework or library requirements? (e.g., React, Vue, Angular)",
        "What is the expected load time for this component, and how is it optimized for performance?",
        "Will this component require third-party integrations? (e.g., analytics, forms, payment gateways)",
    ],
    "Accessibility & Compliance": [
        "Is the component WCAG 2.1 compliant?",
        "Are there keyboard navigable features for accessibility?",
        "Will it support screen readers and other assistive technologies?",
    ],
    "Testing & QA": [
        "What testing strategies will be used? (Unit tests, integration tests, end-to-end tests)",
        "Who is responsible for QA, and what is the acceptance process?",
        "Are there edge cases and error states that need to be tested?",
    ],
    "Publishing & Release Management": [
        "What is the expected deployment path (staging, QA, production)?",
        "Are there rollback and recovery plans in case of deployment failure?",
        "Are there any timelines or content freezes that need to be met?",
        "Will the component require a feature flag for controlled release?",
        "Will there be any training or support needed?",
    ],
}