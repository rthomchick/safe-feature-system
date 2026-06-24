# SAFe Feature Spec System

An AI pipeline that turns a feature description and rough notes into a complete, scored SAFe Feature specification — and then improves it until it passes a 100-point rubric.

Built with Streamlit and the Anthropic Claude API. Designed for a digital product team at ServiceNow producing CAPABILITY, EXPERIENCE, and WEBPAGE features.

---

## What it does

There are two apps:

**`app.py` — Feature Spec Pipeline**
A PM pastes a feature description and any notes they have (meeting notes, Slack threads, strategy docs). The pipeline runs five stages:

1. **Input** — Describe the feature and paste raw notes
2. **Interview** — AI drafts answers for every rubric section from the notes; PM reviews and edits gaps
3. **Generate** — Generates a full SAFe Feature spec from the approved answers
4. **Review** — Scores the spec against a 100-point rubric, section by section
5. **Final** — Shows the improved spec with a before/after score comparison

Between Review and Final, an **Improve** stage runs automatically on any section scoring below 75%. The PM can provide "boost inputs" — context only they have — before the Improver runs. Two improvement passes run sequentially; a light-touch Polish pass fires automatically if the score lands in the 80–89 range.

**`intake_app.py` — Feature Intake Copilot**
A stakeholder-facing conversational interface that collects feature requests without using any product or engineering jargon. Two pages:

- **Stakeholder Intake** — A warm, efficient multi-turn conversation that asks at most two questions per turn, builds an `IntakeRecord`, and ends with a plain-language summary for stakeholder confirmation
- **PM Review** — Shows the intake record, readiness score, and a recommendation (accept / accept with caveats / needs more input), optionally enriched by an Opus advisor for borderline cases

---

## Feature types

The Router classifies every feature into one of three types. The Generator, Reviewer, and Improver all adapt their behavior based on type.

| Type | What it is |
|------|-----------|
| **CAPABILITY** | Backend tools, APIs, integrations, reusable engines |
| **EXPERIENCE** | UI components, interactive frontend features |
| **WEBPAGE** | New pages or updates to existing pages on servicenow.com |

The PM can override the auto-detected type after routing.

---

## Architecture

### Agents

| Agent | Model | Role |
|-------|-------|------|
| Router | Haiku | Classifies feature type (single token output) |
| Draft Answerer | Sonnet | Drafts section answers from raw notes |
| Generator | Sonnet | Writes the full SAFe spec from approved answers |
| Reviewer | Sonnet (or Opus) | Scores spec sections against the rubric |
| Improver | Sonnet (or Opus) | Rewrites weak sections; two passes |
| Polish | Sonnet (or Opus) | Append-only edits for 80–89 range specs |
| Intake Copilot | Sonnet | Manages stakeholder conversation + extraction |

The **Opus Advisor** is available via a sidebar toggle. When enabled, the Reviewer and Improver use `claude-opus-4-6` for deeper reasoning on hard cases.

### Section-isolated re-scoring

After each Improver pass, only the sections that were actually changed are re-scored. Untouched sections carry forward their original scores. This prevents score drift — improving section A cannot cause the Reviewer to reassign points to section B.

A floor clamp prevents re-scored sections from regressing below their original score. A ceiling clamp prevents them from exceeding their rubric maximum.

### Scorecard merging

`_merge_scorecards()` in `app.py` combines a partial re-score into the full scorecard after each pass (Improver pass 1, pass 2, and Polish). The total score is recomputed from merged section scores after each merge.

### Evaluation infrastructure

| Module | Purpose |
|--------|---------|
| `evaluation/token_tracker.py` | Per-agent token and cost tracking across all LLM calls |
| `evaluation/audit_trail.py` | Per-run event log (route, generate, review, improve) |
| `evaluation/cost_guardrails.py` | Per-call cost checks; stops the pipeline if a run exceeds the limit |
| `evaluation/result_store.py` | Persists run results (scores, feature type, pass/fail) to the eval DB |
| `evaluation/eval_db.py` | Dual-mode DB connection: PostgreSQL in production, SQLite for local dev |
| `evaluation/eval_runner.py` | Batch evaluation runner against the golden set |
| `evaluation/golden_set.py` | Reference test cases |

### Request Queue

`pages/request_queue.py` is an alternative pipeline entry point. PMs or automated systems can create feature requests in advance (with optional boost inputs). A PM clicks **Process** to load a request into the pipeline and run it. Results are written back to the request record on completion.

The connector layer (`connectors/postgres.py`) uses the same dual-mode DB as the eval infrastructure.

---

## Project structure

```
app.py                     # Main spec pipeline (5-stage Streamlit app)
intake_app.py              # Standalone intake copilot app

agents/
  router.py                # Feature type classifier
  draft_answerer.py        # Drafts section answers from notes
  generator.py             # Generates the full spec
  reviewer.py              # Scores spec against rubric; section-isolated re-scoring
  improver.py              # Rewrites weak sections; tracks changed sections
  draft_answerer.py

prompts/
  capabilities.py          # CAPABILITY-specific sections and questions
  experiences.py           # EXPERIENCE-specific sections and questions
  webpages.py              # WEBPAGE-specific sections and questions
  reviewer.py              # 100-point rubric definition
  shared.py                # Shared prompt utilities

connectors/
  base.py                  # ConnectorInterface and FeatureRequest dataclass
  postgres.py              # PostgreSQL/SQLite implementation
  example_notion.py        # Example connector stub

evaluation/
  eval_db.py               # DB connection and schema init
  token_tracker.py         # Token/cost tracking
  audit_trail.py           # Per-run event logging
  cost_guardrails.py       # Cost limit enforcement
  result_store.py          # Run result persistence
  eval_runner.py           # Batch eval runner
  golden_set.py            # Reference test cases
  dashboard.py             # Eval results dashboard

pages/
  request_queue.py         # Request Queue page
  pm_review.py             # PM review page (used by main app)
  stakeholder_intake.py    # Stakeholder intake page (used by main app)
  responsible_ai.py        # Responsible AI checklist page

intake_copilot/
  agent.py                 # IntakeCopilot class (conversation + extraction)
  models.py                # IntakeRecord, ConversationManager, ReadinessScorer
  persistence.py           # Intake record persistence
  pipeline_bridge.py       # Bridge to spec pipeline
  pages/                   # Streamlit page renderers for intake app

utils/
  cost_tracker.py          # Cost formatting utilities
  section_names.py         # Scorecard section name normalization
```

---

## Setup

### Requirements

```
anthropic==0.102.0
psycopg2-binary>=2.9.12
streamlit>=1.55.0
pandas>=2.3.0
```

Install into the project venv:

```bash
source ~/Dropbox/ai-projects/venv-rag/bin/activate
pip install -r requirements.txt
```

### Secrets

Create `.streamlit/secrets.toml`:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."

# Optional — PostgreSQL for production. Omit to use SQLite.
DATABASE_URL = "postgresql://user:password@host:5432/dbname"
```

### Running

```bash
# Main spec pipeline
streamlit run app.py

# Intake copilot (separate app)
streamlit run intake_app.py
```

---

## Rubric

The 100-point rubric lives in `prompts/reviewer.py` and is universal across all feature types. The Reviewer adapts its scoring expectations per type using `FEATURE_TYPE_GUIDANCE` in `agents/reviewer.py` — for example, SEO criteria are not penalized for a CAPABILITY (headless backend) as long as the spec explains why and provides equivalent analytics coverage.

Sections and their weights:

| Section | Points |
|---------|--------|
| Feature Definition & Objective | 15 |
| Content Strategy & Value Proposition | 15 |
| SEO, SEM, Analytics | 12 |
| Copywriting, Messaging & Compliance | 10 |
| Campaigns | 10 |
| Engineering, Publishing, QA & Content Model | 15 |
| Studio, Design & Accessibility | 13 |
| Scope, Out of Scope, and Dependencies | 10 |

A score of 90+ is considered ready for leadership review.

---

## Evaluation

Run the batch eval suite against the golden set:

```bash
python -m evaluation.eval_runner
```

View results in the eval dashboard:

```bash
streamlit run evaluation/dashboard.py
```

Smoke test a single pipeline run:

```bash
python -m evaluation.smoke_test
```
