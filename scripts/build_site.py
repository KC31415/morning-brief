"""Build the static site from the database and the saved daily briefs.

    python scripts/build_site.py --out public

GitHub Actions runs this after each refresh and publishes `public/` to GitHub Pages.
"""
import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from morning_brief import sitegen, storage  # noqa: E402
from morning_brief.config import DB_PATH, SUMMARY_PATH, load_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("public"))
    args = parser.parse_args(argv)
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}. Run scripts/refresh.py first.", file=sys.stderr)
        return 1
    start = time.time()
    # Read only: building the site must never change the committed data
    conn = storage.connect_readonly(DB_PATH)
    summary = json.loads(SUMMARY_PATH.read_text()) if SUMMARY_PATH.exists() else None
    pages = sitegen.build(args.out, conn, load_config(), summary, datetime.now(timezone.utc))
    print(f"Wrote {len(pages)} pages to {args.out} in {time.time() - start:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
