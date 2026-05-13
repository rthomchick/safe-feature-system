"""
Stakeholder Intake Chat — page logic.

Call render() to draw the page. set_page_config must be called by the host
script before render() if running inside a multi-page app.

Can also be run as a standalone page:
    streamlit run intake_copilot/pages/stakeholder_intake.py
"""

import streamlit as st

from intake_copilot.agent import IntakeCopilot
from intake_copilot.models import ConversationState


def render() -> None:
    st.title("Feature Intake")
    st.caption("Tell us about the feature you need. We'll ask a few questions to capture the details.")

    # ── Session state init ────────────────────────────────────────────────────
    if "copilot" not in st.session_state:
        st.session_state["copilot"] = IntakeCopilot()
    if "messages" not in st.session_state:
        st.session_state["messages"] = []
    if "intake_done" not in st.session_state:
        st.session_state["intake_done"] = False
    if "greeting_sent" not in st.session_state:
        st.session_state["greeting_sent"] = False

    copilot: IntakeCopilot = st.session_state["copilot"]

    # ── Send greeting once on first load ──────────────────────────────────────
    if not st.session_state["greeting_sent"]:
        greeting = copilot.greeting()
        st.session_state["messages"].append({"role": "assistant", "content": greeting})
        st.session_state["greeting_sent"] = True

    # ── Render conversation history ───────────────────────────────────────────
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── Completion state ──────────────────────────────────────────────────────
    if st.session_state["intake_done"]:
        st.success(
            "Your request has been submitted. "
            "A product manager will review it shortly."
        )
        st.stop()

    # ── Chat input ────────────────────────────────────────────────────────────
    user_input = st.chat_input("Type your message here…")

    if user_input:
        st.session_state["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                reply = copilot.process_turn(user_input)
            st.markdown(reply)

        st.session_state["messages"].append({"role": "assistant", "content": reply})

        if copilot._manager.state == ConversationState.CONFIRMED:
            st.session_state["intake_done"] = True
            st.session_state["copilot"] = copilot
            st.rerun()


# Allow running as a standalone Streamlit page:
#   streamlit run intake_copilot/pages/stakeholder_intake.py
if __name__ == "__main__":
    st.set_page_config(page_title="Feature Intake", layout="centered")
    render()
