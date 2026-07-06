"""Read-only crosswalk seed for Humana. Reads raw Humana commission files, and for
every member row that carries an MBI matching an existing customer (guaranteed
link), writes a carrier_id_crosswalk row (GrpNbr↔customer↔MBI). NEVER runs the
ingest pipeline — writes ONLY carrier_id_crosswalk, so AJ's proven commission data
(amounts/splits/edits) is untouched. Renewal rows (no MBI) are skipped here; they
link at upload time via the key this seed creates.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_humana_crosswalk.py \
      --agency 1 --file "path/to/Humana.xls" [--apply]
Dry-run by default; --apply commits.
"""
import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CarrierIdCrosswalk
from app.commission.resolver import _match_by_mbi


def seed_from_facts(facts, agency_id, apply=False):
    counts = {"seeded": 0, "skipped_no_mbi_match": 0, "skipped_no_grpnbr": 0,
              "already": 0}
    for fact in facts:
        key = (fact.member_group_key or "").strip()
        if not key:
            counts["skipped_no_grpnbr"] += 1
            continue
        if not (fact.mbi or "").strip():
            counts["skipped_no_mbi_match"] += 1
            continue
        customer = _match_by_mbi(fact, agency_id)
        if customer is None:
            counts["skipped_no_mbi_match"] += 1
            continue
        existing = CarrierIdCrosswalk.query.filter_by(
            agency_id=agency_id, carrier="Humana", carrier_key=key).first()
        if existing is not None:
            counts["already"] += 1
            continue
        counts["seeded"] += 1
        if apply:
            db.session.add(CarrierIdCrosswalk(
                agency_id=agency_id, carrier="Humana", carrier_key=key,
                key_kind="grpnbr", customer_id=customer.id,
                mbi=(fact.mbi or None), confidence="exact_id",
                source_note="seed:humana"))
    if apply:
        db.session.commit()
    else:
        db.session.rollback()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", action="append", required=True,
                    help="raw Humana commission file (repeatable)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    from app.commission.sheet_loader import load_sheets
    from app.commission.normalizers import normalize_humana

    app = create_app()
    with app.app_context():
        all_facts = []
        for path in args.file:
            all_facts.extend(normalize_humana(load_sheets(path)))
        counts = seed_from_facts(all_facts, args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] Humana crosswalk seed for agency {args.agency}:")
        for k, v in counts.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
