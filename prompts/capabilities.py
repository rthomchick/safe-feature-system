# prompts/capabilities.py
from prompts.shared import SAFE_PREAMBLE, SAFE_OUTPUT_FORMAT

TYPE_LABEL = "Capability"
TYPE_EXAMPLE = "Example: Build a progressive profiling engine, create an Adobe Target integration, add a CDP event-forwarding pipeline."

PREAMBLE = f"{SAFE_PREAMBLE}\n\nExample:\n- Build a new backend tool, engine, API, integration, or reusable platform capability\n\n{SAFE_OUTPUT_FORMAT}"

SECTIONS = {
    "Strategy & Purpose": [
        "What specific problem does this new tool or capability solve?",
        "Who are the primary users of this tool or capability?",
        "What are the expected user interactions and outcomes?",
        "Is this tool or capability intended for reuse across multiple pages or is it specific to certain pages?",
        "How will reusability impact the design and implementation?",
    ],
    "Design & User Experience": [
        "What design guidelines should this tool or capability follow (e.g., branding, accessibility)?",
        "Are there specific color schemes, fonts, or styles that need to be adhered to?",
        "Are there wireframes, mockups, or prototypes available for review?",
        "How will these visual assets guide the development process?",
        "How will this tool or capability behave across different screen sizes (desktop, mobile, tablet)?",
        "Are there specific breakpoints or responsive design considerations?",
        "What states does this tool or capability need to support? (e.g., hover, active, disabled, error)",
        "How will these states be visually represented?",
        "Does the tool or capability require animations or interactive behaviors?",
        "What are the expected user interactions and feedback mechanisms?",
    ],
    "Content & Localization": [
        "What type of content will this tool or capability display? Is it static, dynamic, or personalized?",
        "How will content be managed and updated?",
        "Are there any localization or translation requirements?",
        "How will localized content be handled and displayed?",
        "Will the content be managed through a CMS (e.g., AEM), or is it hardcoded?",
        "How will content updates be synchronized across different environments?",
        "Are there fallback states if content is missing or fails to load?",
        "How will these fallback states be communicated to the user?",
    ],
    "SEO & Analytics": [
        "Should the tool or capability be indexed by search engines?",
        "How will SEO best practices be implemented?",
        "Are there any structured data requirements (e.g., JSON-LD, Schema.org)?",
        "How will structured data enhance search engine visibility?",
        "What KPIs should be tracked for this tool or capability? (e.g., clicks, form submissions, interactions)",
        "How will these KPIs be measured and reported?",
        "Do we need event tracking for analytics? If so, what specific events?",
        "How will event tracking be implemented and monitored?",
    ],
    "Engineering & Technical Requirements": [
        "What are the technical dependencies for this tool or capability? (APIs, services, CMS integration)",
        "How will these dependencies impact development and deployment?",
        "Is the tool or capability part of a micro-frontend architecture or standalone?",
        "How will the architecture influence scalability and maintainability?",
        "Are there any specific framework or library requirements? (e.g., React, Vue, Angular)",
        "How will these frameworks and libraries be integrated?",
        "What is the expected load time for this tool or capability, and how is it optimized for performance?",
        "What performance metrics will be monitored?",
        "Will this tool or capability require third-party integrations? (e.g., analytics, forms, payment gateways)",
        "How will these integrations be managed and secured?",
    ],
    "Accessibility & Compliance": [
        "Is the tool or capability WCAG 2.1 compliant?",
        "What accessibility features need to be implemented?",
        "Are there keyboard navigable features for accessibility?",
        "How will keyboard interactions be tested and validated?",
        "Will it support screen readers and other assistive technologies?",
        "How will compatibility with assistive technologies be ensured?",
    ],
    "Testing & QA": [
        "What testing strategies will be used? (Unit tests, integration tests, end-to-end tests)",
        "How will testing be documented and tracked?",
        "Who is responsible for QA, and what is the acceptance process?",
        "How will QA feedback be incorporated into the development cycle?",
        "Are there edge cases and error states that need to be tested?",
        "How will these scenarios be identified and addressed?",
    ],
    "Publishing & Release Management": [
        "What is the expected deployment path (staging, QA, production)?",
        "How will deployments be coordinated and communicated?",
        "Are there any timelines or content freezes that need to be met?",
        "Are there rollback and recovery plans in case of deployment failure?",
        "How will rollback procedures be tested and validated?",
        "Will the tool or capability require a feature flag for controlled release?",
        "How will feature flags be managed and monitored?",
        "Will there be any training or support needed?",
    ],
}