"""Seed ONLY the specific out-of-state plan buckets our current members hold.

Tim's call: don't seed whole out-of-state service areas (that's ~473 mostly-empty
buckets); seed just the ~6 distinct plans the tiny out-of-state tail is actually in.
These are REAL, distinct plans with their own out-of-state CMS codes (an SC Humana Gold
Plus is a different plan than the NC one). Name-only — no benefits seeded (we don't
service these yearly). `state` stays on the policy for the upcoming state filter.

If out-of-state grows or you want a full state's plans, use instead:
  seed_plan_buckets.py --states NC,SC,…   (service-area-aware, seeds the whole state)

Verified 2026-07-08 against the live orphan list + CMS CY2026 Landscape.
Idempotent; read-only unless --apply. Run seed_out_of_state_aliases.py + repair after.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_out_of_state_plans.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026

# (carrier, cms_plan_id, plan_type, plan_name) — the exact OOS plans our members hold.
_PLANS = [
    ("UHC",         "H5322-040", "MA",  "AARP Medicare Advantage from UHC SC-0005 (HMO-POS)"),  # Curtis Lowder (SC)
    ("UHC",         "H2001-032", "MA",  "UHC Dual Complete SC-S001 (PPO D-SNP)"),               # Susan Amato (SC)
    ("UHC",         "H4514-014", "MA",  "AARP Medicare Advantage from UHC TX-001P (HMO-POS)"),  # Carolyn Murrey (TX)
    ("UHC",         "H2001-030", "MA",  "UHC Dual Complete WV-S001 (PPO D-SNP)"),               # Susan Barr (WV)
    ("Aetna",       "H3931-101", "MA",  "Aetna Medicare Signature (HMO-POS)"),                  # Sheila Lawrence (VA)
    ("Healthspring","S5617-359", "PDP", "HealthSpring Extra Rx (PDP)"),                          # Patels x3 (SC)
    ("Devoted",     "H7028-002", "MAPD","Devoted CHOICE GIVEBACK South Carolina (PPO)"),         # Tracy Hayden (SC)
]


def seed_plans(agency_id, apply=False):
    counts = {"created": 0, "already": 0}
    for carrier, code, ptype, name in _PLANS:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    cms_plan_id=code, year=YEAR).first()
        if plan is not None:
            counts["already"] += 1
            continue
        counts["created"] += 1
        if apply:
            db.session.add(Plan(agency_id=agency_id, carrier=carrier, cms_plan_id=code,
                                year=YEAR, plan_name=name, plan_type=ptype,
                                status="current", needs_review=False))
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
        res = seed_plans(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] out-of-state plan seed, agency {args.agency}:")
        print(f"  created: {res['created']}")
        print(f"  already: {res['already']}")
        print("  Next: seed_out_of_state_aliases.py --apply, then repair_plan_id_linkage.py --apply")


if __name__ == "__main__":
    main()
