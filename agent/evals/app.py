"""PatchLoop eval suite UI.   streamlit run evals/app.py     (or scripts/eval-app.sh)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

st.set_page_config(page_title="PatchLoop Evals", page_icon=":material/fact_check:", layout="wide",
                   initial_sidebar_state="expanded")

from evals.ui import common  # noqa: E402

PAGES = [
    st.Page("ui/pages/overview.py", title="Overview", icon=":material/dashboard:", default=True),
    st.Page("ui/pages/dataset_page.py", title="Golden dataset", icon=":material/dataset:", url_path="dataset"),
    st.Page("ui/pages/run_page.py", title="Run suite", icon=":material/play_circle:", url_path="run"),
    st.Page("ui/pages/results_page.py", title="Results", icon=":material/fact_check:", url_path="results"),
    st.Page("ui/pages/deepeval_page.py", title="DeepEval", icon=":material/science:", url_path="deepeval"),
    st.Page("ui/pages/ragas_page.py", title="Ragas analysis", icon=":material/analytics:", url_path="ragas"),
    st.Page("ui/pages/compare_page.py", title="Compare runs", icon=":material/compare_arrows:", url_path="compare"),
    st.Page("ui/pages/export_page.py", title="Export", icon=":material/ios_share:", url_path="export"),
]
common.sidebar()
st.navigation(PAGES).run()
