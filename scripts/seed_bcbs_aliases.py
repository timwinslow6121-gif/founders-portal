"""Seed reviewed BCBS BOB-name → bucket aliases for the format-variant legacy names.

The legacy BCBS mis-columned orphans carry their plan NAME in plan_type (the repair
recovers those via _miscolumned_name). Most match a seeded bucket's existing alias, but
~44 are format VARIANTS that differ from the seeded alias by whitespace/punctuation and
so don't match exactly:
  - "Blue Medicare Essential Plus (HMO- POS)"      — note the space in "HMO- POS"
  - "Blue Medicare Freedom+ (PPO)"                 — parens vs the seeded "… PPO"
  - "Healthy Blue + Medicare (HMO-POS D-SNP)"      — vs the seeded "(H9147-001)" form
Rather than fuzz the matcher (risky), we add the exact variant strings as reviewed
aliases on the right buckets. Verified 2026-07-08 against the live orphan list.

Idempotent; read-only unless --apply. Run repair after.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_bcbs_aliases.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026

# (cms_plan_id, raw BOB variant name) → alias to add on the BCBS bucket.
_ALIASES = [
    ("H3449-023", "Blue Medicare Essential Plus (HMO- POS)"),      # 26 (space typo)
    ("H3404-004", "Blue Medicare Freedom+ (PPO)"),                 # 18 (parens)
    ("H9147-001", "Healthy Blue + Medicare (HMO-POS D-SNP)"),      # 8
]


def _has_alias(plan, alias):
    existing = [plan.plan_name.strip().lower()] if plan.plan_name else []
    if plan.plan_name_aliases:
        existing += [a.strip().lower() for a in plan.plan_name_aliases.split(",")]
    return alias.strip().lower() in existing


def seed_aliases(agency_id, apply=False):
    counts = {"added": 0, "already": 0, "no_bucket": 0}
    missing = []
    for code, bob_name in _ALIASES:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier="BCBS",
                                    cms_plan_id=code, year=YEAR).first()
        if plan is None:
            counts["no_bucket"] += 1
            missing.append(f"BCBS {code} ({bob_name})")
            continue
        if _has_alias(plan, bob_name):
            counts["already"] += 1
            continue
        counts["added"] += 1
        if apply:
            plan.plan_name_aliases = (
                bob_name if not plan.plan_name_aliases
                else f"{plan.plan_name_aliases},{bob_name}")
    counts["missing_buckets"] = missing
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
        res = seed_aliases(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] BCBS format-variant alias seed, agency {args.agency}:")
        print(f"  added:     {res['added']}")
        print(f"  already:   {res['already']}")
        print(f"  no_bucket: {res['no_bucket']}")
        for m in res["missing_buckets"]:
            print(f"    MISSING BUCKET: {m}")
        print("  Next: re-run scripts/repair_plan_id_linkage.py --agency 1 --year 2026 --apply")


if __name__ == "__main__":
    main()
