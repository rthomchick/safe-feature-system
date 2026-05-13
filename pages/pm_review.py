import streamlit as st
from intake_copilot.pages.pm_review import render

st.set_page_config(page_title="PM Review", layout="wide")
render()
