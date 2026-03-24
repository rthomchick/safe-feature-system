# prompts/webpages.py
from prompts.shared import SAFE_PREAMBLE, SAFE_OUTPUT_FORMAT

TYPE_LABEL = "Webpage"
TYPE_EXAMPLE = "Example: Create a new ITSM product page, update the marquee on the ITSM page, build a Knowledge 2025 campaign landing page."

PREAMBLE = f"{SAFE_PREAMBLE}\n\nExamples:\n- Create a new product page on ServiceNow.com\n- Update the marquee on the ITSM page\n\n{SAFE_OUTPUT_FORMAT}"

SECTIONS = {
    "Content Strategy & Purpose": [
        "What is the primary objective of this page? (Lead generation, awareness, product information, etc.)",
        "Who is the target audience, and what stage of the buyer's journey are they in?",
        "What key message or value proposition should this page communicate?",
        "What problem are we solving for the user with this page?",
        "Are there specific calls-to-action (CTAs) that we want users to take?",
    ],
    "Studio & Design": [
        "Are there existing design guidelines or templates we should follow?",
        "What type of media (images, videos, animations) will be included?",
        "Are there any accessibility considerations (WCAG compliance) that need to be addressed?",
        "How should the user experience be optimized for both desktop and mobile?",
        "Should we consider interactive elements (e.g., forms, calculators, interactive maps)?",
    ],
    "Copywriting": [
        "What is the tone and voice required for the copy? (Professional, conversational, technical, etc.)",
        "What are the key SEO keywords we should prioritize in the copy?",
        "Are there existing marketing materials or messaging guidelines that the copy should align with?",
        "Do we need customer testimonials or case studies on this page?",
        "Is legal or compliance review required for any of the copy?",
    ],
    "SEO & Analytics": [
        "What keywords and phrases are we optimizing for?",
        "What is the SEO strategy for the page? (Internal linking, metadata, schema markup, etc.)",
        "Are there any SEO best practices we should implement for image optimization and page speed?",
        "What are the KPIs and metrics we want to track for this page? (Conversion rate, bounce rate, time on page, etc.)",
        "Will we need any custom event tracking or UTM parameters for analytics?",
        "Are there any vanity URLs or canonical URL requirements that need to be defined for SEO purposes?",
        "If the page is temporary (e.g., for a campaign or event), what is the plan for post-campaign?",
        "Do we need to set up redirects, archive the content, hide from search, or decommission the page after it expires?",
    ],
    "Engineering & Publishing": [
        "What is the timeline for development and publishing?",
        "Are there any dependencies on backend systems (CMS, integrations, API calls)?",
        "Will this page require new components, or can we leverage existing ones?",
        "Are there any A/B testing requirements for this page?",
        "How do we handle version control and future updates to this page?",
        "What are the number of pages expected to be updated or created?",
        "What are the number of geo sites that we will roll out?",
        "Are there any timelines or content freezes that need to be met?",
        "Does this page require any specific taxonomy setup or tagging structure?",
        "Will the QA team be involved in testing? If so, what are the specific QA requirements for layout, content accuracy, functionality, or analytics tracking?",
        "Does this page require any custom embed code or front-end logic from the development team? If yes, please specify which sections.",
        "Has the page been built and tested in the appropriate environments (e.g., Stage, Production)? Are any additional validations needed before publishing?",
        "Are there rollback and recovery plans in case of publishing failure?",
    ],
}