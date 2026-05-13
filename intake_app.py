# intake_app.py
# Standalone intake copilot app — stakeholder intake + PM review only.
# Run: streamlit run intake_app.py

import streamlit as st

st.set_page_config(
    page_title="Feature Intake Copilot",
    page_icon="🤖",
    layout="wide",
)

from intake_copilot.pages.stakeholder_intake import render as render_intake
from intake_copilot.pages.pm_review import render as render_pm_review

intake_page = st.Page(render_intake, title="Stakeholder Intake", icon="💬", url_path="intake", default=True)
pm_page = st.Page(render_pm_review, title="PM Review", icon="🔍", url_path="pm_review")

pg = st.navigation([intake_page, pm_page])
pg.run()
