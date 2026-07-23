"""DRY-RUN Devoted BOB import: runs the REAL import pipeline (_detect_carrier,
parse_carrier_file, _dedupe_bob_records, _import_bob_row) against prod, then
ROLLS BACK. Reports new/updated/skipped + unresolvable + a before/after active
count. Writes NOTHING (rollback at the end). --apply is NOT accepted here on
purpose; use scripts/import_bob_file.py to actually commit.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/devoted_import_dryrun.py
"""
import os
from datetime import date
from app import create_app
from app.extensions import db
from app.models import ImportBatch, Policy

FILE = "docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx"
AGENCY_ID = 1


def main():
    app = create_app()
    with app.app_context():
        from app.upload import (_detect_carrier, _dedupe_bob_records,
                                _import_bob_row)
        from app.parsers import parse_carrier_file

        before = Policy.query.filter_by(carrier="Devoted", status="active").count()

        filename = os.path.basename(FILE)
        carrier = _detect_carrier(FILE, filename)
        print("detected carrier:", carrier)

        batch = ImportBatch(agency_id=AGENCY_ID, carrier=carrier, filename=filename,
                            status="pending")
        db.session.add(batch)
        db.session.flush()

        records = parse_carrier_file(carrier, FILE)
        records = _dedupe_bob_records(records)
        print("records after dedup:", len(records))

        today = date.today()
        unresolvable = []
        plan_review = []
        counts = {"new": 0, "updated": 0, "skipped": 0, "error": 0}
        for rec in records:
            sp = db.session.begin_nested()
            try:
                res = _import_bob_row(rec, batch, AGENCY_ID, None, today,
                                      unresolvable, plan_review=plan_review)
                counts[res] = counts.get(res, 0) + 1
                sp.commit()
            except Exception as e:
                sp.rollback()
                counts["error"] += 1
                if counts["error"] <= 5:
                    print("  row error:", type(e).__name__, str(e)[:120])

        db.session.flush()
        after = Policy.query.filter_by(carrier="Devoted", status="active").count()

        print()
        print("=== DRY-RUN RESULT (rolled back) ===")
        print("  new:", counts["new"], "| updated:", counts["updated"],
              "| skipped:", counts["skipped"], "| error:", counts["error"])
        print("  unresolvable rows:", len(unresolvable))
        print("  plan-review (no bucket) rows:", len(plan_review))
        print("  Devoted active BEFORE:", before, "-> AFTER (in this rolled-back tx):", after)

        db.session.rollback()
        print("\nROLLED BACK — nothing written.")


if __name__ == "__main__":
    main()
