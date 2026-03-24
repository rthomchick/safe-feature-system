The analysis you're doing:
For each of the three generation prompts, map it into this structure:
Section Name# of QuestionsUnique to this type?NotesStrategy & Purpose5Capabilities onlyIncludes reusabilityDesign & UX10Shared (all 3)—...
You're looking for four things:

Shared sections — these become reusable infrastructure
Type-specific sections — these live in capabilities.py, experiences.py, webpages.py
Total question count per type — tells you how long each interview takes and where the Draft Answerer earns its keep
Output format — all three should share the same SAFe structure (Title, Description, Scope, Out of Scope, Solution Approach, Acceptance Criteria, Dependencies)

The syllabus gives you a head start on what Capabilities looks like. Your job now is to do the same analysis for Experiences and Webpages from your actual Notion prompts, since those are your real source of truth.
Document your analysis here in a simple scratch file — prompt_analysis.md in the project root — before you touch any Python. This prevents you from encoding wrong assumptions into your data structures.