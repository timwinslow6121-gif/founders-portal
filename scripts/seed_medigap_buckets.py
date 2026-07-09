"""Seed the missing Medigap (Medicare Supplement) plan buckets.

Medigap is NOT in the CMS MA/PDP Landscape (it's state-filed separately), so
seed_plan_buckets doesn't create these — they're seeded here by (carrier, plan letter).
Medigap benefits are STANDARDIZED by letter (Plan G is Plan G, Plan N is Plan N) — the
letter fully defines the benefits — so these are name/letter-only buckets (no benefit
data needed). find_plan_bucket matches medigap by plan_letter at any year.

Seeds the letters our members actually hold that lack a bucket (verified 2026-07-08):
  - UHC Plan N, BCBS Plan N  (UHC/BCBS Plan G buckets already exist)
  - Humana Plan G            (Humana had no medigap bucket)

Idempotent; read-only unless --apply. Run repair after.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_medigap_buckets.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026   # medigap matches at any year; store at 2026 to sit with the other buckets.

# (carrier, plan_letter, plan_name) — name is descriptive only; the LETTER is identity.
_BUCKETS = [
    ("UHC",    "N", "Medicare Supplement Plan N"),
    ("BCBS",   "N", "Supplement Plan N"),
    ("Humana", "G", "Humana Med Supp Plan G"),
]


def seed_buckets(agency_id, apply=False):
    counts = {"created": 0, "already": 0}
    for carrier, letter, name in _BUCKETS:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    plan_letter=letter, year=YEAR).first()
        if plan is not None:
            counts["already"] += 1
            continue
        counts["created"] += 1
        if apply:
            db.session.add(Plan(agency_id=agency_id, carrier=carrier, plan_letter=letter,
                                cms_plan_id=None, year=YEAR, plan_name=name,
                                plan_type="medigap", status="current", needs_review=False))
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = seed_buckets(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] medigap bucket seed, agency {args.agency}:")
        print(f"  created: {res['created']}")
        print(f"  already: {res['already']}")
        print("  Next: re-run scripts/repair_plan_id_linkage.py --agency 1 --year 2026 --apply")


if __name__ == "__main__":
    main()
