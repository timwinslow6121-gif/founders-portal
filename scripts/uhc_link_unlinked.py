"""Link UHC active policies with plan_id=NULL to their real Plan bucket, using the
authoritative BOB (contract-pbp per member). Read-only by default; --apply to write.

Root cause of the 44 "Unlinked / needs plan": commission-import policies have a blank
plan_name, so the free-text plan linker had nothing to match. The BOB HAS the real
contract-pbp for every active member → look them up by MBI/member_id, find the matching
Plan bucket, set Policy.plan_id.

Run on the VPS (BOB at /tmp/uhc_bob.xlsx):
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/uhc_link_unlinked.py [--apply]
"""
import sys
from collections import Counter
import pandas as pd

from app import create_app
from app.extensions import db
from app.models import Policy, Plan

BOB_PATH = "/tmp/uhc_bob.xlsx"


def norm(s):
    return str(s).strip().upper() if s is not None and str(s) != "nan" else ""


def find_bucket(cms_dash):
    """cms_dash like 'H5253-184'. Match a Plan by cms_plan_id in dash OR underscore form."""
    contract, _, pbp = cms_dash.partition("-")
    under = f"{contract}_{pbp}"
    return Plan.query.filter(Plan.cms_plan_id.in_([cms_dash, under])).first()


def main(apply):
    app = create_app()
    with app.app_context():
        bob = pd.read_excel(BOB_PATH, header=2, dtype=str).dropna(how="all")
        bob = bob[bob["policyTermDate"] == "2300-01-01"]
        by_mbi, by_member = {}, {}
        for _, r in bob.iterrows():
            cms = f"{norm(r['contract'])}-{norm(r['pbp'])}"
            name = norm(r["planName"])
            if norm(r["mbiNumber"]):
                by_mbi[norm(r["mbiNumber"])] = (cms, name)
            if norm(r["memberNumber"]):
                by_member[norm(r["memberNumber"])] = (cms, name)

        unlinked = Policy.query.filter_by(carrier="UHC", status="active", plan_id=None).all()
        print(f"{'APPLY' if apply else 'DRY-RUN'} — UHC unlinked policies: {len(unlinked)}\n")

        linked = 0
        missing_bucket = Counter()
        not_in_bob = 0
        for p in unlinked:
            rec = (by_mbi.get(norm(p.mbi)) or by_member.get(norm(p.member_id))
                   or by_mbi.get(norm(p.member_id)))
            if not rec:
                not_in_bob += 1
                continue
            cms, name = rec
            bucket = find_bucket(cms)
            if not bucket:
                missing_bucket[cms] += 1
                continue
            print(f"  pid {p.id} -> {cms} ({name[:32]}) bucket id={bucket.id} '{bucket.plan_name}'")
            if apply:
                p.plan_id = bucket.id
                # backfill the blank plan_name from the bucket for display consistency
                if not p.plan_name:
                    p.plan_name = bucket.plan_name
            linked += 1

        print(f"\n  linkable now: {linked}")
        print(f"  not in BOB: {not_in_bob}")
        if missing_bucket:
            print(f"  MISSING Plan bucket (need to seed): {sum(missing_bucket.values())}")
            for cms, n in missing_bucket.most_common():
                print(f"     {n:3d}  {cms}")

        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — no changes written.")


def diagnose():
    """Read-only: why aren't the unlinked policies matching the BOB?"""
    app = create_app()
    with app.app_context():
        bob = pd.read_excel(BOB_PATH, header=2, dtype=str).dropna(how="all")
        bob = bob[bob["policyTermDate"] == "2300-01-01"]
        bob_mbi = {norm(x) for x in bob["mbiNumber"]}
        bob_member = {norm(x) for x in bob["memberNumber"]}
        from app.models import Customer
        unlinked = Policy.query.filter_by(carrier="UHC", status="active", plan_id=None).all()
        no_mbi = sum(1 for p in unlinked if not norm(p.mbi))
        synth = sum(1 for p in unlinked if str(p.member_id).startswith("uhc::"))
        inbob = 0
        for p in unlinked:
            if norm(p.mbi) in bob_mbi or norm(p.member_id) in bob_member or norm(p.member_id) in bob_mbi:
                inbob += 1
        print(f"unlinked total: {len(unlinked)}")
        print(f"  no mbi: {no_mbi}")
        print(f"  synthetic uhc:: member_id: {synth}")
        print(f"  matched in BOB by mbi/member: {inbob}")
        print("\nsample:")
        for p in unlinked[:15]:
            c = Customer.query.get(p.customer_id) if p.customer_id else None
            nm = c.full_name if c else "?"
            hit = norm(p.mbi) in bob_mbi or norm(p.member_id) in bob_member or norm(p.member_id) in bob_mbi
            print(f"  pid {p.id} | {nm} | mbi={p.mbi} member_id={p.member_id} | {p.plan_type} | in_bob={hit}")


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        diagnose()
    else:
        main("--apply" in sys.argv)
