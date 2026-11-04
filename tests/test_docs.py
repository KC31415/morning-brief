"""The README and build notes should point at things that exist and say what the code does."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
NOTES = (ROOT / "docs" / "build-notes.md").read_text()


def test_readme_links_and_images_exist():
    for target in re.findall(r"\]\(((?!https?://)[^)#]+)\)", README):
        assert (ROOT / target).exists(), target


def test_readme_no_longer_claims_most_bugs_came_from_real_data():
    assert "Most bugs only appeared on real data" not in README


def test_judgment_index_points_at_real_entries():
    entries = {int(n) for n in re.findall(r"^## (\d+)\. ", NOTES, re.M)}
    index = NOTES[NOTES.index("## Judgment calls at a glance"):NOTES.index("## 1. ")]
    cited = {int(n) for cell in re.findall(r"\| ([\d, ]+) \|\n", index) for n in cell.split(",")}
    assert cited and cited <= entries


def test_build_notes_are_numbered_in_order():
    numbers = [int(n) for n in re.findall(r"^## (\d+)\. ", NOTES, re.M)]
    assert numbers == list(range(1, len(numbers) + 1))


def test_vix_notice_says_it_is_freds_required_text():
    app = (ROOT / "app.py").read_text()
    assert "as FRED requires it to be shown" in app and "Reprinted with permission" in app
