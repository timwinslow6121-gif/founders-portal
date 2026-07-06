"""One-time cleanup: collapse legacy Humana commission stubs into their real
customer, using the carrier_id_crosswalk built by seed_humana_crosswalk.py. A stub
is merged ONLY when the crosswalk corroborates it maps to a DIFFERENT real
(stub=False) customer — lonely stubs are never touched. Uses the existing audited
merge_customers (fill-blanks-only, reattaches all children, refuses contradictions).

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/cleanup_humana_stubs.py \
      --agency 1 [--apply]
Dry-run by default.
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Customer, CarrierIdCrosswalk, User


def plan_cleanup(agency_id):
    """Return [{stub_id, keeper_id, grpnbr}] safe merges. A legacy Humana stub is
    paired to a keeper when the stub's MBI (stored in humana_id by the old importer)
    matches a Humana crosswalk row whose customer is a DIFFERENT real (stub=False)
    customer. Only corroborated pairs are returned; lonely stubs are never listed."""
    # map: MBI -> (real customer_id, GrpNbr) from crosswalk rows pointing at real customers
    real_by_mbi = {}
    for row in CarrierIdCrosswalk.query.filter_by(agency_id=agency_id, carrier="Humana"):
        if not (row.mbi or "").strip():
            continue
        cust = Customer.query.get(row.customer_id)
        if cust is not None and not cust.stub:
            real_by_mbi[row.mbi.strip()] = (cust.id, row.carrier_key)
    pairs = []
    stubs = Customer.query.filter_by(agency_id=agency_id, stub=True,
                                     source="commission_import").all()
    for stub in stubs:
        mbi = (stub.humana_id or stub.mbi or "").strip()
        if not mbi:
            continue
        hit = real_by_mbi.get(mbi)
        if hit and hit[0] != stub.id:
            pairs.append({"stub_id": stub.id, "keeper_id": hit[0], "grpnbr": hit[1]})
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        from app.customers import merge_customers
        actor = User.query.filter_by(agency_id=args.agency).first()
        pairs = plan_cleanup(args.agency)
        print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {len(pairs)} stub→real merges")
        for p in pairs:
            print(f"  stub {p['stub_id']} → keeper {p['keeper_id']} (GrpNbr {p['grpnbr']})")
            if args.apply:
                merge_customers(p["keeper_id"], [p["stub_id"]], args.agency, actor)
        if args.apply:
            db.session.commit()


if __name__ == "__main__":
    main()
