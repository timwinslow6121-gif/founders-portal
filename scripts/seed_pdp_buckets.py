"""Seed the NC standalone-PDP (Part D) plan buckets — HAND-MAINTAINED.

The CMS MA/MAPD Landscape file does NOT include PDP plans, so seed_plan_buckets can't
create these. But there are only ~10 PDP plans an NC agent sells, so they're easy to
list here and update by hand each year (Tim's call). One bucket per (carrier, cms_plan_id,
year). Idempotent; read-only unless --apply.

To maintain: add/adjust rows in _PDP_PLANS each Annual Enrollment (contract-plan code +
name). cms_plan_id is the 2-part contract-plan (S####-###), dash form.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_pdp_buckets.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026

# NC standalone PDPs. Names + codes VERIFIED against the authoritative CMS sheet
# "2026 North Carolina Stand-Alone Prescription Drug Plan Organizations"
# (docs/Medicare Landscape Files/PDP Info/). Extend/adjust by hand each AEP.
# NOTE: S5617-359 (HealthSpring Extra Rx SC) + S5601-017 (SilverScript Plus) are NOT on
# the 2026 NC sheet but real members hold them (SC out-of-state / grandfathered) — kept.
_PDP_PLANS = [
    ("Aetna",        "S5601-016", "SilverScript Choice (PDP)"),
    ("Aetna",        "S5601-017", "SilverScript Plus (PDP)"),        # not on 2026 NC sheet; real members
    ("BCBS",         "S5540-002", "Blue Medicare Rx Standard (PDP)"),
    ("BCBS",         "S5540-004", "Blue Medicare Rx Enhanced (PDP)"),
    ("Healthspring", "S5617-217", "HealthSpring Assurance Rx (PDP)"),
    ("Healthspring", "S5617-358", "HealthSpring Extra Rx (PDP)"),    # NC
    ("Healthspring", "S5617-359", "HealthSpring Extra Rx (PDP)"),    # SC (out-of-state)
    ("Humana",       "S5884-133", "Humana Basic Rx Plan (PDP)"),
    ("Humana",       "S5884-187", "Humana Value Rx Plan (PDP)"),
    ("Humana",       "S5884-154", "Humana Premier Rx Plan (PDP)"),
    ("UHC",          "S5921-353", "AARP Medicare Rx Saver from UHC (PDP)"),
    ("UHC",          "S5921-390", "AARP Medicare Rx Preferred from UHC (PDP)"),
    ("Wellcare",     "S4802-081", "WellCare Classic (PDP)"),
    ("Wellcare",     "S4802-143", "WellCare Value Script (PDP)"),
]


def seed_pdps(agency_id, apply=False):
    counts = {"created": 0, "already": 0}
    for carrier, code, name in _PDP_PLANS:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    cms_plan_id=code, year=YEAR).first()
        if plan is not None:
            counts["already"] += 1
            continue
        counts["created"] += 1
        if apply:
            db.session.add(Plan(agency_id=agency_id, carrier=carrier, cms_plan_id=code,
                                year=YEAR, plan_name=name, plan_type="PDP",
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
        res = seed_pdps(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] NC PDP bucket seed, agency {args.agency}:")
        print(f"  created: {res['created']}")
        print(f"  already: {res['already']}")


if __name__ == "__main__":
    main()
