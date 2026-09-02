#!/usr/bin/env python3
"""Pivot ALL-benefit-data.csv into a side-by-side 2026 vs 2027 comparison.

Derived artifact -- never hand-edit the output. Correct values in the source
CSV (docs/plan-data-sheets/ALL-benefit-data.csv) and re-run.

No change detection: the chart shows both years side by side and the reader
compares them visually.

Usage:
    python3 scripts/build_plan_comparison.py
    python3 scripts/build_plan_comparison.py --carrier Devoted
    python3 scripts/build_plan_comparison.py --all-benefits
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Works both inside the founders-portal repo and as a standalone bundle.
if (HERE / "data" / "ALL-benefit-data.csv").exists():
    ROOT = HERE
    SRC = HERE / "data" / "ALL-benefit-data.csv"
    OUT_DIR = HERE / "data"
else:
    ROOT = HERE.parent
    SRC = ROOT / "docs" / "plan-data-sheets" / "ALL-benefit-data.csv"
    OUT_DIR = ROOT / "docs" / "plan-data-sheets"

PRIOR_YEAR, LOOK_YEAR = "2026", "2027"

# Chart row order. Money/cost items first, then extras -- the order agents
# read a plan in. Only benefits present in BOTH years by default; the two
# vocabularies differ (2026=CMS clinical detail, 2027=first-look marketing).
BENEFIT_ORDER = [
    "Premium",
    "Part B giveback",
    "Medical deductible",
    "Max out-of-pocket",
    "PCP",
    "Specialist",
    "Referrals",
    "Inpatient hospital",
    "Outpatient surgery (ASC)",
    "Emergency room",
    "Urgent care",
    "Ambulance (ground)",
    "Lab services",
    "Diagnostic radiology",
    "Rx deductible",
    "Rx retail (30-day)",
    "Dental - allowance",
    "Vision - eyeglasses",
    "Hearing aids",
    "OTC allowance",
    "Transportation",
    "Meals",
    "Fitness",
    "Wellness programs",
    "Service area",
    "Key notes",
]


def load(src=SRC):
    with open(src, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build(rows, carrier=None, all_benefits=False):
    """Return (records, skipped_plans).

    A record is one plan x benefit with both years' values side by side.
    """
    # (cms_code, benefit) -> {year: value}
    cell = defaultdict(dict)
    meta = {}
    for r in rows:
        code = r["CMS Code"].strip()
        if carrier and r["Carrier"].strip().lower() != carrier.lower():
            continue
        cell[(code, r["Benefit"].strip())][r["Year"].strip()] = r["Value"].strip()
        # Prefer the first-look name/carrier when present -- plans get renamed.
        if code not in meta or r["Year"] == LOOK_YEAR:
            meta[code] = {"Carrier": r["Carrier"].strip(), "Plan Name": r["Plan Name"].strip()}

    codes_with_look = {c for (c, _), yv in cell.items() if LOOK_YEAR in yv}
    codes_both = {
        c for c in codes_with_look
        if any(PRIOR_YEAR in yv for (cc, _), yv in cell.items() if cc == c)
    }
    skipped = sorted(codes_with_look - codes_both)

    if all_benefits:
        order = BENEFIT_ORDER + sorted(
            {b for (_, b) in cell} - set(BENEFIT_ORDER)
        )
    else:
        order = BENEFIT_ORDER

    records = []
    for code in sorted(codes_both):
        for benefit in order:
            yv = cell.get((code, benefit))
            if not yv:
                continue
            v26, v27 = yv.get(PRIOR_YEAR, ""), yv.get(LOOK_YEAR, "")
            if not v26 and not v27:
                continue
            records.append({
                "Carrier": meta[code]["Carrier"],
                "CMS Code": code,
                "Plan Name": meta[code]["Plan Name"],
                "Benefit": benefit,
                PRIOR_YEAR: v26,
                LOOK_YEAR: v27,
            })
    return records, skipped


def write_csv(records, path):
    cols = ["Carrier", "CMS Code", "Plan Name", "Benefit", PRIOR_YEAR, LOOK_YEAR]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(records)


def write_json(records, path):
    """One object per plan -- the shape a Canva autofill payload wants."""
    plans = defaultdict(lambda: {"benefits": []})
    for r in records:
        p = plans[r["CMS Code"]]
        p["carrier"] = r["Carrier"]
        p["cms_code"] = r["CMS Code"]
        p["plan_name"] = r["Plan Name"]
        p["benefits"].append({
            "benefit": r["Benefit"],
            "y2026": r[PRIOR_YEAR],
            "y2027": r[LOOK_YEAR],
        })
    payload = {
        "prior_year": PRIOR_YEAR,
        "look_year": LOOK_YEAR,
        "notice": (
            "2027 values are preliminary carrier First Look data, not yet "
            "verified against published CMS data. Internal agent use only."
        ),
        "plans": list(plans.values()),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--carrier", help="limit to one carrier")
    ap.add_argument("--all-benefits", action="store_true",
                    help="include benefits present in only one year")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    rows = load()
    records, skipped = build(rows, args.carrier, args.all_benefits)

    suffix = f"-{args.carrier.lower()}" if args.carrier else ""
    csv_path = args.out_dir / f"comparison-{PRIOR_YEAR}-{LOOK_YEAR}{suffix}.csv"
    json_path = args.out_dir / f"comparison-{PRIOR_YEAR}-{LOOK_YEAR}{suffix}.json"
    write_csv(records, csv_path)
    write_json(records, json_path)

    plans = len({r["CMS Code"] for r in records})
    print(f"{len(records)} rows across {plans} plans")
    print(f"  {csv_path.relative_to(ROOT)}")
    print(f"  {json_path.relative_to(ROOT)}")
    if skipped:
        print(f"\n{len(skipped)} plans have {LOOK_YEAR} data but no {PRIOR_YEAR} "
              f"baseline (new plans, or renamed CMS codes):")
        for c in skipped:
            print(f"  {c}")


if __name__ == "__main__":
    main()
