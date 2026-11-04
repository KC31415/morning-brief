"""Entry point kept so the existing Streamlit Cloud deployment, which runs app.py, keeps working.

The Streamlit app lives in streamlit_app/app.py; the main site is the static build on GitHub Pages.
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "streamlit_app" / "app.py"), run_name="__main__")
