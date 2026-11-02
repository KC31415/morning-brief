"""app.py's Streamlit calls must match the version requirements.txt promises."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_app_does_not_use_deprecated_container_width():
    assert "use_container_width" not in (ROOT / "app.py").read_text()


def test_streamlit_floor_supports_width_stretch():
    # st.altair_chart first accepts width="stretch" in 1.51; st.dataframe in 1.49
    floor = re.search(r"^streamlit>=(\d+)\.(\d+)", (ROOT / "requirements.txt").read_text(), re.M)
    assert (int(floor.group(1)), int(floor.group(2))) >= (1, 51)


def test_tests_do_not_touch_the_real_database():
    # conftest.py checks this after the whole run; this guards against it being removed.
    assert (ROOT / "tests" / "conftest.py").exists()
