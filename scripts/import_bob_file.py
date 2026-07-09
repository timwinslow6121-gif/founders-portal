"""Headless BOB import — runs the SAME pipeline as the /upload/bulk route, for a file,
without a browser. Reuses the real, tested functions (_detect_carrier, parse_carrier_file,
_dedupe_bob_records, _import_bob_row) so behavior matches the UI exactly: per-row
savepoints, chronological dedup, AOR handling, customer upsert, plan-bucket sorting, and
the unresolvable/plan_review collection.

Admin-style upload (agent_id unset, resolved per-row) when --admin; else attributes to
--agent-id. Creates a real ImportBatch. Read-only planning is NOT offered here (a BOB
import is inherently write) — so ALWAYS DB-backup first and diff counts after.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/import_bob_file.py \
      --agency 1 --admin --file "docs/Carrier BOB DL/.../Humana Book of business.xlsx"
"""
import argparse
import os

from app import create_app
from app.extensions import db
from app.models import ImportBatch


def import_bob(agency_id, filepath, admin=True, agent_id=None):
    from app.upload import _detect_carrier, _dedupe_bob_records, _import_bob_row
    from app.parsers import parse_carrier_file
    from datetime import date
    import json

    today = date.today()
    filename = os.path.basename(filepath)
    carrier = _detect_carrier(filepath, filename)
    bulk_agent_id = None if admin else agent_id

    batch = ImportBatch(agency_id=agency_id, carrier=carrier, filename=filename,
                        uploaded_by_id=(agent_id or 1), status="pending")
    db.session.add(batch)
    db.session.commit()

    records = parse_carrier_file(carrier, filepath)
    records = _dedupe_bob_records(records)
    new_count = updated_count = skipped = 0
    unresolvable, plan_review, errs = [], [], []
    plan_year = today.year
    for rec in records:
        try:
            with db.session.begin_nested():
                outcome = _import_bob_row(rec, batch, agency_id, bulk_agent_id, today,
                                          unresolvable, plan_year=plan_year,
                                          plan_review=plan_review)
            if outcome == "new": new_count += 1
            elif outcome == "updated": updated_count += 1
            else: skipped += 1
        except Exception as e:
            errs.append(f"{rec.get('carrier')} {rec.get('member_id')}: {e}")
    if unresolvable:
        batch.unresolvable_json = json.dumps(unresolvable)
    batch.record_count = len(records)
    batch.new_count = new_count
    batch.updated_count = updated_count
    batch.status = "success"
    db.session.commit()

    return {"carrier": carrier, "batch_id": batch.id, "records": len(records),
            "new": new_count, "updated": updated_count, "skipped": skipped,
            "unresolvable": len(unresolvable), "plan_review": len(plan_review),
            "errors": errs}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--admin", action="store_true", help="admin upload (per-row agent resolve)")
    ap.add_argument("--agent-id", type=int, default=None)
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = import_bob(args.agency, args.file, admin=args.admin, agent_id=args.agent_id)
        print(f"BOB import [{res['carrier']}] batch {res['batch_id']}:")
        for k in ("records", "new", "updated", "skipped", "unresolvable", "plan_review"):
            print(f"  {k}: {res[k]}")
        if res["errors"]:
            print(f"  errors: {len(res['errors'])}")
            for e in res["errors"][:15]:
                print(f"    {e}")


if __name__ == "__main__":
    main()
