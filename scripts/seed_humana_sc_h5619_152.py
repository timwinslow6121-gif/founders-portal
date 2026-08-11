"""Seed the ONE out-of-state bucket Humana H5619-152 (SC) and link its 3 policies.

WHY A ONE-PLAN SCRIPT INSTEAD OF `seed_plan_buckets.py --states SC`:
that would create all 21 SC Humana buckets, 20 of which nobody in the book holds —
cluttering the plan list with plans that will never have a member. Seed only what
is actually enrolled; add more the same way if SC business grows.

WHY THESE ARE LEGITIMATE (Tim, 2026-08-11): **CMS bases enrollment on the member's
PERMANENT address (what SSA has on file), while the portal stores the MAILING
address.** So an NC mailing address on an SC plan is NOT contradictory data — it is
the normal snowbird / family-address case. Both writing agents are contracted in SC:
  pid 62    Jane Bost           mail SC  — agent Timothy Winslow
  pid 11841 Jagdishchandra Shah mail NC  — agent Anjana Patel
  pid 12223 Spencena Wragg      mail NC  — agent Anjana Patel
There is existing precedent for out-of-state buckets: UHC H5322-040/H5322-044/
H2001-032 (SC), H2001-030 (WV), Devoted H7028-002 (SC).

⚠ PLAN TYPE COMES FROM CMS, NOT FROM THE POLICIES. All three policies carry
`plan_type='MA'`, but that field is known-unreliable (see BACKLOG "DATA TRAP":
Humana is 81.5% MA-typed because the parser copies the carrier's product code, and
UHC/HealthSpring do the same). CMS CY2026 Landscape is authoritative and says
H5619-152 is **MA-PD** — a drug plan — so the bucket is seeded `mapd`. Trusting the
policies here would have baked the parser bug into a new bucket.

CMS CY2026 facts for H5619-152 (verified in the Landscape file):
  Plan Name  : Humana Gold Plus H5619-152 (HMO)
  Type       : MA-PD (HMO, Local CCP)      States: SC only — NC has NO H5619 plans
  Org        : Humana Inc. / ARCADIAN HEALTH PLAN, INC.
  Stars 3.5  : premium $0.00, drug deductible $350.00, MOOP in-network $7,200.00

Seeds ONE bucket at year=2026 (idempotent — re-running finds it and only links),
then links the 3 policies. Dry-run by default; --apply commits.

Run on the VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
    scripts/seed_humana_sc_h5619_152.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Plan, Policy

CARRIER = "Humana"
CMS_ID = "H5619-152"          # canonical DASH form — underscore orphans it from the sorter
YEAR = 2026
PLAN_NAME = "Humana Gold Plus H5619-152 (HMO)"   # CMS official name
PLAN_TYPE = "mapd"            # CMS says MA-PD; the policies' 'MA' is the known-bad field
TARGET_POLICY_IDS = (62, 11841, 12223)


def main(apply):
    app = create_app()
    with app.app_context():
        agency_id = app.config.get("DEFAULT_AGENCY_ID", 1)
        print(f"{'APPLY' if apply else 'DRY-RUN'} — seed {CARRIER} {CMS_ID} (SC) + link "
              f"{len(TARGET_POLICY_IDS)} policies\n")

        # ---- 1. the bucket (idempotent) --------------------------------------
        bucket = Plan.query.filter_by(agency_id=agency_id, carrier=CARRIER,
                                      cms_plan_id=CMS_ID, year=YEAR).first()
        if bucket:
            print(f"  bucket EXISTS: id={bucket.id} '{bucket.plan_name}' "
                  f"[{bucket.plan_type}]")
        else:
            print(f"  {'CREATE' if apply else 'would create'}: {CARRIER} {CMS_ID} "
                  f"year={YEAR} '{PLAN_NAME}' [{PLAN_TYPE}] status=current")
            if apply:
                bucket = Plan(agency_id=agency_id, carrier=CARRIER, cms_plan_id=CMS_ID,
                              year=YEAR, plan_name=PLAN_NAME, plan_type=PLAN_TYPE,
                              status="current", needs_review=False)
                db.session.add(bucket)
                db.session.flush()
                print(f"    created id={bucket.id}")

        # ---- 2. link the policies --------------------------------------------
        print()
        linked = 0
        for pid in TARGET_POLICY_IDS:
            p = db.session.get(Policy, pid)
            if not p:
                print(f"  pid {pid}: NOT FOUND (skip)")
                continue
            # SAFETY: pin carrier/status and NEVER overwrite an existing link.
            if p.carrier != CARRIER or p.status != "active":
                print(f"  pid {pid}: carrier={p.carrier} status={p.status} (skip, SAFETY)")
                continue
            if p.plan_id is not None:
                print(f"  pid {pid}: already linked to plan_id={p.plan_id} (skip, SAFETY)")
                continue
            if p.agency_id != agency_id:
                print(f"  pid {pid}: agency {p.agency_id} (skip, SAFETY)")
                continue
            cust = (Customer.query.filter_by(id=p.customer_id, agency_id=agency_id).first()
                    if p.customer_id else None)
            nm = (cust.full_name if cust else None) or p.full_name or "?"
            st = (cust.state if cust else None) or "?"
            print(f"  pid {pid:>5}  {nm[:26]:<26} mail={st:<3} -> {CMS_ID}"
                  + (f" bucket {bucket.id}" if bucket else " (bucket pending --apply)"))
            if apply and bucket:
                p.plan_id = bucket.id
                if not (p.plan_name or "").strip():
                    p.plan_name = PLAN_NAME
            linked += 1

        print(f"\n  LINKABLE: {linked} of {len(TARGET_POLICY_IDS)}")
        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing committed. Re-run with --apply to commit.")
        return 0


if __name__ == "__main__":
    sys.exit(main("--apply" in sys.argv))
