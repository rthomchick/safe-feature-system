# intake_copilot/test_scenarios/eng_graphql_schema.py
# Scenario 3 — Engineering lead requesting a GraphQL schema for the comparison module.
# RAW_INPUT:   unstructured stakeholder message as received
# CASE_INPUT:  ground truth — what a skilled PM would extract from a full conversation
# BOOST_INPUTS: section-specific detail the PM adds during review (feeds the Generator)

RAW_INPUT = """\
We need to add a defined GraphQL schema for the product comparison module. Currently the \
frontend is making 3 separate REST calls that could be consolidated. Schema should support \
filtering by product category, feature-by-feature comparison for up to 4 products, and \
real-time pricing lookups.\
"""

CASE_INPUT = """\
Feature type: CAPABILITY

Feature description: Implement a GraphQL schema for the product comparison module, \
consolidating three existing REST API endpoints into a single, efficient query interface. \
The schema should support: product filtering by category, feature-by-feature comparison for \
up to 4 products simultaneously, and real-time pricing data resolution. This is an \
API-layer capability that improves frontend performance and developer experience for any \
team building comparison experiences.

Target user: Frontend engineering teams building product comparison experiences, and \
indirectly, website visitors who use the product comparison tool. The primary consumer is \
the web platform team; secondary consumers include the mobile team and any partner \
integrations that use the comparison API.

Business justification: Performance improvement and developer efficiency. The current \
3-call REST pattern creates waterfall latency on the comparison page (estimated \
800–1200ms total round-trip). A consolidated GraphQL query reduces this to a single \
round-trip (target: under 400ms). Additionally, the defined schema makes the comparison \
module self-documenting, reducing onboarding time for new frontend developers and enabling \
the mobile team to build comparison features without reverse-engineering the REST endpoints.

Success metrics: API response time for comparison queries (target: p95 under 400ms vs. \
current estimated 800–1200ms). Reduction in frontend code complexity (lines of code, \
number of API calls per page load). Developer adoption: number of teams consuming the \
GraphQL schema within 6 months. Comparison page load time improvement as measured by Core \
Web Vitals (LCP).

Constraints: Must maintain backward compatibility with existing REST endpoints during \
migration period. GraphQL schema must be versioned. Real-time pricing lookups must respect \
the pricing API rate limits (currently 100 req/s). Must handle the product catalog's \
current data model without requiring catalog restructuring.

Existing context: Three REST endpoints currently serve the comparison module: /products \
(catalog listing), /products/compare (side-by-side data), /pricing (real-time pricing). \
The frontend makes these calls sequentially. No GraphQL infrastructure currently exists — \
this would be the first GraphQL endpoint, requiring schema registry setup.\
"""

BOOST_INPUTS = """\
Technical architecture: GraphQL gateway should use Apollo Server with DataLoader for \
batching pricing lookups. Schema stitching is not needed for v1 — single schema serving \
the comparison domain. Pricing resolver should implement a 30-second cache to stay within \
rate limits.

Acceptance criteria: Schema passes Apollo schema validation. All three existing REST \
endpoint capabilities are replicable via GraphQL queries. Comparison query for 4 products \
returns in under 400ms at p95. Schema includes deprecation annotations for fields planned \
to change in the next catalog model update.

Migration plan: REST endpoints remain active for 6 months post-launch. Frontend teams \
migrate incrementally — no big-bang cutover. Usage metrics on both REST and GraphQL \
endpoints to track migration progress.\
"""
