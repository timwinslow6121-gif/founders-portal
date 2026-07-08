"""Seed the authoritative NC plan buckets from the CMS CY2026 Landscape. One Plan per
(carrier, cms_plan_id, year). Idempotent upsert; does NOT overwrite human-verified plan
data (leaves existing benefit fields alone — only fills name/type on create). CMS
Organization Marketing Name → our carrier label. Read-only unless apply=True.

COMPLEMENTARY to the EXISTING scripts/sync_cms_plan_data.py: THIS script CREATES the
buckets (identity/name/type); sync_cms_plan_data.py ENRICHES existing buckets with CMS
benefits (premium/MOOP/stars/copays) and skips-as-'unmatched' any plan with no bucket.
Today only ~36 of ~187 NC buckets exist, so sync's 'unmatched' list is huge; after this
seed runs, run sync and its 'unmatched' drops to ~0. Deploy order: seed (this) → sync.
Do NOT fold creation into sync — keep create and enrich as separate one-job scripts.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_plan_buckets.py \
      --agency 1 --file "docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv" [--apply]
"""
import argparse
import csv

from app import create_app
from app.extensions import db
from app.models import Plan

CMS_YEAR = 2026

# CMS "Organization Marketing Name" (or parent org) → our carrier label.
_ORG_TO_CARRIER = {
    "humana": "Humana",
    "unitedhealthcare": "UHC",
    "aetna medicare": "Aetna",
    "aetna": "Aetna",
    "blue cross and blue shield of north carolina": "BCBS",
    "healthspring": "Healthspring",
    "cigna": "Healthspring",
    "devoted health": "Devoted",
}

# CMS Plan Type → our plan_type bucket-kind.
def _plan_type(cms_type: str) -> str:
    t = (cms_type or "").strip().lower()
    if "pdp" in t or "prescription" in t:
        return "PDP"
    if "hmo" in t or "ppo" in t or "pos" in t or "local" in t or "regional" in t:
        return "MA"
    return (cms_type or "other").strip()[:32]


def _carrier_of(org: str):
    return _ORG_TO_CARRIER.get((org or "").strip().lower())


def seed_buckets_from_rows(rows, agency_id, apply=False):
    """rows = iterable of CMS Landscape row dicts. Upsert one Plan per (carrier,
    ContractPlanID, year). NC only; unknown org → skipped."""
    counts = {"created": 0, "updated": 0, "skipped": 0}
    seen = set()   # (carrier, cms_plan_id) handled this run
    for row in rows:
        if (row.get("State Territory Abbreviation") or "").strip().upper() != "NC":
            counts["skipped"] += 1
            continue
        carrier = _carrier_of(row.get("Organization Marketing Name")
                              or row.get("Parent Organization Name"))
        cms_id = (row.get("ContractPlanID") or "").strip().upper()
        if not carrier or not cms_id:
            counts["skipped"] += 1
            continue
        key = (carrier, cms_id)
        if key in seen:
            continue                      # one bucket per plan, ignore extra county rows
        seen.add(key)
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    cms_plan_id=cms_id, year=CMS_YEAR).first()
        if plan is None:
            counts["created"] += 1
            if apply:
                db.session.add(Plan(
                    agency_id=agency_id, carrier=carrier, cms_plan_id=cms_id,
                    year=CMS_YEAR, plan_name=(row.get("Plan Name") or cms_id),
                    plan_type=_plan_type(row.get("Plan Type")),
                    status="current", needs_review=False))
        else:
            counts["updated"] += 1        # exists already — leave human data intact
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        with open(args.file, encoding="latin-1") as f:
            rows = list(csv.DictReader(f))
        res = seed_buckets_from_rows(rows, args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] NC plan-bucket seed, agency {args.agency}:")
        for k, v in res.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
