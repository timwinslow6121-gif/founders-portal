#!/usr/bin/env python3
"""One-time: create the shared Google Sheet from ALL-benefit-data.csv.

Creates one tab per carrier (long format) plus a read-only Plan Index tab.
Run this ONCE to seed the Sheet. After that the Sheet is the source of
truth -- use pull_plan_data.py to get data back out.

Setup:
    1. Google Cloud console -> enable Google Sheets API + Google Drive API
    2. Create a service account, download its JSON key
    3. Save the key as  .google-service-account.json  (gitignored)

Usage:
    .venv-sheets/bin/python scripts/push_plan_data_to_sheet.py \
        --share tim@foundersinsuranceagency.com \
        --share admin@foundersinsuranceagency.com
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    sys.exit("Missing deps. Run:\n  .venv-sheets/bin/pip install gspread google-auth")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "plan-data-sheets" / "ALL-benefit-data.csv"
INDEX = ROOT / "docs" / "plan-data-sheets" / "plan-index.csv"
KEY = ROOT / ".google-service-account.json"

TITLE = "Medicare Plan Data 2026-2027 (NC)"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column order in each carrier tab. Verified By / Verified Date / Notes are
# for humans to fill in as they check values against carrier sources.
COLS = ["CMS Code", "Plan Name", "Year", "Benefit", "Value",
        "Source", "Verified By", "Verified Date", "Notes"]

README_ROWS = [
    ["Medicare Plan Data 2026-2027 (NC)"],
    [],
    ["WHAT THIS IS"],
    ["Shared source of truth for 2026 and 2027 NC Medicare plan benefit data."],
    ["One tab per carrier. Edit directly -- changes are live for everyone."],
    [],
    ["HOW TO EDIT"],
    ["1. Find the carrier tab.",],
    ["2. Add or correct a row. One row = one plan + one year + one benefit."],
    ["3. Put your name in 'Verified By' and today's date in 'Verified Date'"],
    ["   when you have checked a value against a carrier source."],
    ["4. Use 'Notes' for anything unusual (segment quirks, county limits, etc)."],
    [],
    ["SOURCE COLUMN -- what the value is based on"],
    ["CMS", "Published, CMS-approved data. Authoritative."],
    ["FL", "Carrier First Look. PRELIMINARY -- CMS may supersede it."],
    [],
    ["WHEN FINAL CMS PBP DATA ARRIVES (around December)"],
    ["Do NOT delete the First Look rows. Add the CMS row alongside and set"],
    ["Source=CMS. Where CMS differs from the First Look, note it -- that tells"],
    ["us which plans we may have described incorrectly during AEP prep."],
    [],
    ["GOTCHAS"],
    ["- 2026 data came from CMS (deep clinical detail). 2027 came from carrier"],
    ["  First Look sheets (marketing-shaped). The benefit lists DIFFER."],
    ["- A blank value means 'not in that year's source', NOT $0."],
    ["- Values are free text ($455 days 1-6). Do not assume they are numbers."],
    ["- Aetna, BCBS and Wellcare have no 2027 rows yet -- their First Look"],
    ["  material exists only as PDFs and has not been transcribed."],
    [],
    ["COMPLIANCE"],
    ["CMS marketing rules apply. Naming dental / vision / hearing / OTC makes a"],
    ["piece regulated MARKETING once it reaches a beneficiary -- needs a TPMO"],
    ["disclaimer and carrier filing. Internal agent use is fine."],
    ["2027 values are preliminary and must be labelled as such on any export."],
]


def client():
    if not KEY.exists():
        sys.exit(
            f"No service account key at {KEY}\n\n"
            "Create one: Google Cloud console -> IAM -> Service Accounts ->\n"
            "Create key (JSON). Enable the Sheets API and Drive API for the\n"
            f"project. Save the JSON as {KEY.name} in the repo root."
        )
    creds = Credentials.from_service_account_file(str(KEY), scopes=SCOPES)
    return gspread.authorize(creds)


def load_rows():
    with open(SRC, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--share", action="append", default=[],
                    help="email to give edit access (repeatable)")
    ap.add_argument("--title", default=TITLE)
    args = ap.parse_args()

    gc = client()
    rows = load_rows()

    by_carrier = defaultdict(list)
    for r in rows:
        by_carrier[r["Carrier"].strip()].append(r)

    sh = gc.create(args.title)
    print(f"Created: {args.title}")

    # README tab
    ws = sh.sheet1
    ws.update_title("README")
    ws.update(values=README_ROWS, range_name="A1")
    ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
    for hdr in ("A3", "A7", "A14", "A18", "A23", "A31"):
        ws.format(hdr, {"textFormat": {"bold": True}})

    # One tab per carrier
    for carrier in sorted(by_carrier):
        crows = by_carrier[carrier]
        crows.sort(key=lambda r: (r["CMS Code"], r["Year"], r["Benefit"]))
        data = [COLS] + [[r.get(c, "") for c in COLS] for r in crows]
        ws = sh.add_worksheet(title=carrier, rows=len(data) + 200, cols=len(COLS))
        ws.update(values=data, range_name="A1")
        ws.freeze(rows=1)
        ws.format("A1:I1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": .15, "green": .43, "blue": .65},
        })
        ws.format("A1:I1", {"textFormat": {
            "bold": True,
            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
        }})
        print(f"  {carrier:14} {len(crows):5} rows")

    # Plan Index tab (reference; regenerate rather than hand-edit)
    if INDEX.exists():
        with open(INDEX, newline="", encoding="utf-8") as fh:
            idx = list(csv.reader(fh))
        ws = sh.add_worksheet(title="Plan Index", rows=len(idx) + 50,
                              cols=len(idx[0]))
        ws.update(values=idx, range_name="A1")
        ws.freeze(rows=1)
        ws.format(f"A1:{chr(64+len(idx[0]))}1", {"textFormat": {"bold": True}})
        print(f"  {'Plan Index':14} {len(idx)-1:5} plans")

    for email in args.share:
        sh.share(email, perm_type="user", role="writer", notify=False)
        print(f"  shared with {email}")

    print(f"\nSheet ID: {sh.id}")
    print(f"URL:      {sh.url}")
    print(f"\nSave the ID for pull_plan_data.py:")
    print(f"  echo 'PLAN_SHEET_ID={sh.id}' >> .env")


if __name__ == "__main__":
    main()
