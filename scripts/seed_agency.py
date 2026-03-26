#!/usr/bin/env python3
"""
scripts/seed_agency.py

One-time script: seeds one Agency row ("Founders Insurance Agency") and
backfills agency_id on all existing rows in all 9 tables.

Run this on the VPS AFTER:
  - flask db upgrade (migrations 001 + 002 applied)
  - pgloader has loaded all production data from SQLite

Run BEFORE:
  - flask db upgrade (migration 003 — adds NOT NULL constraint)

Usage:
  export FLASK_APP=wsgi.py
  python scripts/seed_agency.py
"""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Agency


TABLES = [
    'users', 'policies', 'customers', 'customer_notes',
    'customer_contacts', 'customer_aor_history',
    'agent_carrier_contracts', 'pharmacies', 'import_batches'
]


def main():
    app = create_app()
    with app.app_context():
        # Check if Agency already seeded
        existing = Agency.query.first()
        if existing:
            print(f"Agency already exists: {existing.name} (id={existing.id}). Skipping seed.")
            agency_id = existing.id
        else:
            agency = Agency(name="Founders Insurance Agency")
            db.session.add(agency)
            db.session.flush()  # get the id before commit
            agency_id = agency.id
            print(f"Created Agency: 'Founders Insurance Agency' (id={agency_id})")

        # Backfill agency_id on all tables
        for table in TABLES:
            result = db.session.execute(
                db.text(f"UPDATE {table} SET agency_id = :aid WHERE agency_id IS NULL"),
                {"aid": agency_id}
            )
            print(f"  {table}: {result.rowcount} rows updated")

        db.session.commit()
        print("Done. All agency_id columns backfilled.")
        print(f"Now run: flask db upgrade  (to apply migration 003 — NOT NULL constraint)")


if __name__ == "__main__":
    main()
