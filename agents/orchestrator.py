# agents/orchestrator.py
# Orchestration is handled by app.py via Streamlit session state.
# The stage router in app.py coordinates all agents in sequence.
# See: stage_input → stage_draft → stage_generate → stage_review → stage_improve → stage_final