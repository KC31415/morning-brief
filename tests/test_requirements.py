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


def _pins(path):
    pins = {}
    for line in (ROOT / path).read_text().splitlines():
        line = line.split("#")[0].strip()
        if "==" in line:
            name, version = line.split("==")
            pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def _floors():
    floors = {}
    for line in (ROOT / "requirements.txt").read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*>=\s*([\d.]+)", line)
        if m:
            floors[m.group(1).lower().replace("_", "-")] = m.group(2)
    return floors


def _version(v):
    parts = [int(p) for p in re.findall(r"\d+", v)[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def test_lock_pins_every_requirement_at_or_above_its_floor():
    # The scheduled refresh installs the lock, so it must cover everything requirements.txt asks for
    lock = _pins("requirements-lock.txt")
    for name, floor in _floors().items():
        assert name in lock, f"{name} missing from requirements-lock.txt"
        assert _version(lock[name]) >= _version(floor), f"{name} {lock[name]} is below the floor {floor}"


def test_minimum_constraint_is_the_streamlit_floor():
    floor = _floors()["streamlit"]
    assert _version(_pins("constraints-min.txt")["streamlit"]) == _version(floor)


def test_ci_tests_both_minimum_and_latest():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "deps: [latest, minimum]" in ci
    assert "-c constraints-min.txt" in ci


def test_refresh_installs_the_lock():
    assert "pip install -r requirements-lock.txt" in (ROOT / ".github" / "workflows" / "refresh.yml").read_text()
