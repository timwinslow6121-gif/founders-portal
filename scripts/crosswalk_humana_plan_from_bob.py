"""Humana crosswalk plan backfill — resolve blank-plan Humana orphans from the Humana BOB.

Humana commission and BOB share NO ID (commission = numeric PID; BOB = 'Humana ID' H####),
so the orphans (real customers whose commission created the policy) can't be matched by
member_id. But the customer's identity CAN bridge to the BOB two safe ways:
  1. EXACT Humana ID — some orphan customers carry the Humana ID (or an MBI) in
     `customers.humana_id` (Humana's MBI is stored there by design). If that value is a
     Humana ID present in the BOB, it's an exact 1:1 match.
  2. UNIQUE full name — if the orphan's name appears EXACTLY ONCE in the BOB, that BOB
     member is unambiguously them.
ANY shared name (2+ BOB members with that name) is AMBIGUOUS and left for review — even
if both are on the same plan, they may be two different people (Tim's rule). Never guess.

⚠ Unique-name is a SEMI-SAFE bridge for NOW (Tim). The PERMANENT link is Humana ID / MBI.
This script builds toward that: every match it makes is persisted to carrier_id_crosswalk
BY HUMANA ID when the customer has one, so as customer records get enriched with their
Humana ID / MBI, future matching shifts from name → ID automatically. Once customers carry
their real IDs, prefer the ID tier and retire name-matching.

The BOB plan_name embeds the CMS code (HUMANA GOLD PLUS HMO POS H1036-335), so once the
name is filled, find_plan_bucket sorts it by code — never creating a bucket. A matched
orphan's Humana ID is persisted to carrier_id_crosswalk so future imports self-heal.

Read-only unless --apply. Run after a DB backup; dry-run + review the match list first.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/crosswalk_humana_plan_from_bob.py \
      --agency 1 --bob "docs/Carrier BOB DL/July 2026 period/Humana/Humana Book of business.xlsx" [--apply]
"""
import argparse
from collections import Counter, defaultdict

from app import create_app
from app.extensions import db
from app.models import Policy, Customer, CarrierIdCrosswalk
from app.parsers import parse_carrier_file
from app.plan_bucket import find_plan_bucket


def _nkey(name):
    return " ".join((name or "").upper().split())


def _bob_indexes(bob_path):
    """Return (by_humana_id, by_name) from the Humana BOB. by_name maps name→list so we
    can tell unique from shared."""
    recs = parse_carrier_file("Humana", bob_path)
    by_hid, by_name = {}, defaultdict(list)
    for r in recs:
        hid = str(r.get("member_id") or "").strip().upper()
        rec = {"plan_name": r.get("plan_name") or ""}
        if hid:
            by_hid[hid] = rec
        by_name[_nkey(r.get("full_name"))].append(rec)
    return by_hid, by_name


def _link(pol, bob_plan_name, year, agency_id, apply):
    """Fill the orphan's plan from the BOB name + sort into its bucket. Returns True if a
    bucket matched (linked), False if no bucket (leftover)."""
    rec = {"plan_name": bob_plan_name, "plan_type": pol.plan_type or ""}
    b = find_plan_bucket("Humana", rec, year, agency_id)
    if not b["plan_id"]:
        return False
    if apply:
        pol.plan_id = b["plan_id"]
        pol.contract_code = b["contract_code"]
        pol.plan_year = b["plan_year"]
        pol.plan_name = bob_plan_name
    return True


def _persist_crosswalk(agency_id, humana_id, customer_id, apply):
    if not apply or not humana_id:
        return
    exists = CarrierIdCrosswalk.query.filter_by(
        agency_id=agency_id, carrier="Humana", carrier_key=humana_id).first()
    if exists is None and humana_id not in {o.carrier_key for o in db.session.new
                                            if isinstance(o, CarrierIdCrosswalk)}:
        db.session.add(CarrierIdCrosswalk(
            agency_id=agency_id, carrier="Humana", carrier_key=humana_id,
            key_kind="member_id", customer_id=customer_id, confidence="exact_id",
            source_note="humana BOB plan crosswalk"))


def crosswalk(agency_id, bob_path, year=2026, apply=False):
    by_hid, by_name = _bob_indexes(bob_path)
    counts = {"linked_id": 0, "linked_name": 0, "ambiguous": 0,
              "not_in_bob": 0, "no_bucket": 0}
    not_in_bob = []
    no_bucket = Counter()
    orphans = (Policy.query
               .filter(Policy.agency_id == agency_id, Policy.carrier == "Humana",
                       Policy.status == "active", Policy.plan_id.is_(None))
               .all())
    for pol in orphans:
        cust = db.session.get(Customer, pol.customer_id) if pol.customer_id else None
        hid = (cust.humana_id or "").strip().upper() if cust else ""
        name = cust.full_name if cust else None

        # Tier 1 — exact Humana ID
        if hid and hid in by_hid:
            if _link(pol, by_hid[hid]["plan_name"], year, agency_id, apply):
                counts["linked_id"] += 1
                _persist_crosswalk(agency_id, hid, pol.customer_id, apply)
            else:
                counts["no_bucket"] += 1; no_bucket[by_hid[hid]["plan_name"]] += 1
            continue

        # Tier 2 — unique name
        hits = by_name.get(_nkey(name), [])
        if len(hits) == 1:
            if _link(pol, hits[0]["plan_name"], year, agency_id, apply):
                counts["linked_name"] += 1
                if hid:
                    _persist_crosswalk(agency_id, hid, pol.customer_id, apply)
            else:
                counts["no_bucket"] += 1; no_bucket[hits[0]["plan_name"]] += 1
            continue

        if len(hits) > 1:
            counts["ambiguous"] += 1        # shared name — never guess
        else:
            counts["not_in_bob"] += 1
            not_in_bob.append(name or f"(policy {pol.member_id})")

    counts["not_in_bob_names"] = sorted(set(not_in_bob))
    counts["no_bucket_plans"] = [f"{n} ({k})" for n, k in no_bucket.most_common()]
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--bob", required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = crosswalk(args.agency, args.bob, year=args.year, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Humana plan crosswalk from BOB, agency {args.agency}:")
        print(f"  linked by Humana ID:   {res['linked_id']}")
        print(f"  linked by unique name: {res['linked_name']}")
        print(f"  ambiguous (shared name, skipped): {res['ambiguous']}")
        print(f"  not in this BOB:       {res['not_in_bob']}")
        print(f"  matched but no bucket: {res['no_bucket']}")
        if res["no_bucket_plans"]:
            print("    (BOB plan has no seeded bucket:)")
            for n in res["no_bucket_plans"]:
                print(f"      {n}")
        if res["not_in_bob_names"]:
            print(f"  --- {len(res['not_in_bob_names'])} not-in-BOB names (leave orphaned, spot-check): ---")
            for n in res["not_in_bob_names"]:
                print(f"      {n}")


if __name__ == "__main__":
    main()
