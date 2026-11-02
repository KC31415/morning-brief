"""Load the instrument list and settings from config/instruments.yaml."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "instruments.yaml"
DB_PATH = ROOT / "data" / "brief.db"
SUMMARY_PATH = ROOT / "data" / "summary.json"
REPORT_PATH = ROOT / "data" / "check_report.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    for inst in cfg["instruments"]:
        inst.setdefault("source", "yfinance")
        inst.setdefault("calendar", cfg["sessions"][inst["session"]]["calendar"])
    return cfg
