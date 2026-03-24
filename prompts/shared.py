# prompts/shared.py

SAFE_PREAMBLE = """As a Digital Product Manager, we are using Scaled Agile Framework \
and working on a new feature.

What it is: A Feature is a unit of functionality that delivers user or business \
value and supports an Epic. A Feature is often something a user can see, interact \
with, or benefit from directly.

Why it's important: Features are the building blocks of value delivery. They are \
concrete enough for engineering and design to scope and build, but strategic enough \
to map to business outcomes."""

SAFE_OUTPUT_FORMAT = """Please use this information to create the following:

**SAFe Feature**

Provide one SAFe Feature, using the following structure and definitions for each:

- **Title**: A concise and descriptive name that stakeholders can quickly understand.
- **Description**: A short, user-focused narrative stating what the feature does, \
for whom, and why. It must be small enough to deliver within a single Program Increment.
- **Scope (In-Scope)**: What this feature will deliver—functional scope, systems \
impacted, or specific deliverables.
- **Out of Scope**: Clear exclusions—what this feature intentionally avoids or defers.
- **Solution Approach**: A high-level view of how the team will build or implement \
this feature. Mention any platforms, systems, integrations, or frameworks used.
- **Acceptance Criteria**: Generate as many user stories as needed. Each user story \
will have one user story and a table with multiple acceptance criteria, sorted by priority.

**User Story Format:**
"As a [persona], I want to [action], so I can [benefit]."

**Acceptance Criteria Format using Gherkin syntax:**
- Given [context]
- When [event or interaction]
- Then [expected outcome]

Also include a prioritization method based on:
- Business value
- Customer need
- Complexity
- Risk
- Strategic fit

Ensure stories reflect real use cases from the notes provided.

**Priority Format** (highest to lowest): P0, P1, P2, P3, P4

- **Dependencies**: Any internal or external teams, systems, or processes that this \
feature relies on. Mention dependencies that could impact timing or sequencing.

Please ensure the Feature is structured clearly and written for cross-functional teams \
including engineering, devops, design, content, QA, SEO and analytics. Format the \
output so it can be easily used in a SAFe tool."""