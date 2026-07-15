"""Seed the 2 missing UHC Plan buckets and link their policies.

Of the 44 "Unlinked / needs plan", 42 are the held cross-carrier rows (active in DB but
NOT in the authoritative BOB — deferred to the switcher pass). Only 2 are genuinely
BOB-active and just lack a Plan bucket:
  - pid 10074 Michael Blanton — H2001-893 "UnitedHealthcare Group Medicare Advantage" (MA, group/retiree)
  - pid 10117 Jana Benson     — DVHO0002 "DVH 1000" (UHC dental/vision/hearing ancillary)

Seed those 2 buckets (idempotent) and set the policies' plan_id. Dry-run by default.

Run on the VPS:
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/uhc_seed_link_2_buckets.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Plan, Policy

PERPETUAL = 0

# (policy_id, cms_plan_id, year, plan_name, plan_type)
TARGETS = [
    (10074, "H2001-893", 2026, "UnitedHealthcare Group Medicare Advantage", "ma"),
    (10117, "DVHO0002",  PERPETUAL, "DVH 1000", "dvh"),
]


def get_or_create_bucket(agency_id, cms, year, name, ptype, apply):
    existing = (Plan.query
                .filter_by(agency_id=agency_id, carrier="UHC", cms_plan_id=cms, year=year)
                .first())
    if existing:
        print(f"  bucket exists: {cms} (id {existing.id})")
        return existing
    print(f"  {'CREATE' if apply else 'would create'} bucket: UHC {cms} '{name}' [{ptype}] year={year}")
    if not apply:
        return None
    p = Plan(agency_id=agency_id, carrier="UHC", cms_plan_id=cms, year=year,
             plan_name=name, plan_type=ptype, status="current",
             needs_review=False, is_commissionable=True, has_unresolved_conflicts=False)
    db.session.add(p)
    db.session.flush()
    return p


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — seed 2 UHC buckets + link 2 policies\n")
        for pid, cms, year, name, ptype in TARGETS:
            pol = db.session.get(Policy, pid)
            if not pol:
                print(f"  pid {pid}: NOT FOUND (skip)")
                continue
            if pol.carrier != "UHC" or pol.status != "active":
                print(f"  pid {pid}: carrier {pol.carrier} status {pol.status} (skip, SAFETY)")
                continue
            bucket = get_or_create_bucket(aid, cms, year, name, ptype, apply)
            if apply and bucket:
                pol.plan_id = bucket.id
                if not pol.plan_name:
                    pol.plan_name = name
                print(f"    linked pid {pid} -> bucket {bucket.id}")
        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — no changes written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
