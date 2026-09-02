#!/usr/bin/env python3
"""Fetch the shared Google Sheet down to local CSVs, then rebuild the
2026-vs-2027 comparison. Run this before making charts so you are working
from current data.

Setup (one time):
    1. Get the service account JSON key from Tim
    2. Save it next to this script as  .google-service-account.json
    3. Save the Sheet ID:  echo 'PLAN_SHEET_ID=<id>' > .plan-sheet-id

Usage:
    python3 pull_plan_data.py
    python3 pull_plan_data.py --sheet-id <id>
"""
import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("Missing deps. Run:\n  pip install gspread google-auth")

HERE = Path(__file__).resolve().parent
# Works standalone (bundle/) or inside the repo (scripts/).
if (HERE / "data").is_dir():
    ROOT, OUT = HERE, HERE / "data"
else:
    ROOT, OUT = HERE.parent, HERE.parent / "docs" / "plan-data-sheets"

KEY = ROOT / ".google-service-account.json"
IDFILE = ROOT / ".plan-sheet-id"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

COLS = ["CMS Code", "Carrier", "Plan Name", "Year", "Benefit", "Value",
        "Source", "Verified By", "Verified Date", "Notes"]
SKIP_TABS = {"README", "Plan Index"}


def sheet_id(cli_value):
    if cli_value:
        return cli_value
    if os.environ.get("PLAN_SHEET_ID"):
        return os.environ["PLAN_SHEET_ID"]
    if IDFILE.exists():
        txt = IDFILE.read_text().strip()
        return txt.split("=", 1)[-1].strip() if "=" in txt else txt
    sys.exit(
        f"No Sheet ID. Either pass --sheet-id <id>, or:\n"
        f"  echo '<id>' > {IDFILE}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet-id")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="skip regenerating the comparison file")
    args = ap.parse_args()

    if not KEY.exists():
        sys.exit(f"No service account key at {KEY}\nAsk Tim for the JSON key file.")

    creds = Credentials.from_service_account_file(str(KEY), scopes=SCOPES)
    sh = gspread.authorize(creds).open_by_key(sheet_id(args.sheet_id))
    print(f"Fetching from: {sh.title}")

    OUT.mkdir(parents=True, exist_ok=True)
    all_rows, index_rows = [], None

    for ws in sh.worksheets():
        if ws.title == "Plan Index":
            index_rows = ws.get_all_values()
            continue
        if ws.title in SKIP_TABS:
            continue

        records = ws.get_all_records()
        if not records:
            print(f"  {ws.title:14}     0 rows (empty)")
            continue

        for r in records:
            r.setdefault("Carrier", ws.title)
            if not str(r.get("Carrier", "")).strip():
                r["Carrier"] = ws.title
            all_rows.append({c: str(r.get(c, "")).strip() for c in COLS})

        # per-carrier slice
        path = OUT / f"benefits-{ws.title}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS)
            w.writeheader()
            w.writerows([r for r in all_rows if r["Carrier"] == ws.title])
        print(f"  {ws.title:14} {len(records):5} rows")

    if not all_rows:
        sys.exit("No data rows found -- check the Sheet has carrier tabs.")

    src = OUT / "ALL-benefit-data.csv"
    with open(src, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWrote {src.name} ({len(all_rows)} rows)")

    if index_rows:
        path = OUT / "plan-index.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(index_rows)
        print(f"Wrote {path.name} ({len(index_rows)-1} plans)")

    if not args.no_rebuild:
        build = ROOT / "build_plan_comparison.py"
        if not build.exists():
            build = ROOT / "scripts" / "build_plan_comparison.py"
        if build.exists():
            print()
            subprocess.run([sys.executable, str(build)], check=False)

    try:
        meta = sh.get_lastUpdateTime()
        print(f"\nSheet last edited: {meta}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
