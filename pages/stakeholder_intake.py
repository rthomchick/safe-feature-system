import streamlit as st
from intake_copilot.pages.stakeholder_intake import render

st.set_page_config(page_title="Feature Intake", layout="centered")
render()
