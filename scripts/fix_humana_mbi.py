"""
scripts/fix_humana_mbi.py

One-time backfill: convert mbi='' (empty string) to NULL on both the
policies and customers tables.

Background: Humana masks MBIs in their BOB export as 'XXXXX...' strings.
The parser historically converted these to empty strings ('') instead of
NULL. PostgreSQL treats '' as a non-NULL value, so a partial unique index
on customers.mbi WHERE mbi IS NOT NULL would still flag duplicate empty
strings as a violation on future imports.

This script normalizes all historical empty-string MBIs to NULL so that:
  1. The partial unique index (migration 014) can be applied cleanly.
  2. Humana customers without MBIs can coexist in the table without
     triggering constraint violations.

Usage (on VPS):
    cd /var/www/founders-portal

    # Dry-run (default) — shows counts, makes no changes:
    ./venv/bin/python3 scripts/fix_humana_mbi.py

    # Apply changes:
    ./venv/bin/python3 scripts/fix_humana_mbi.py --execute
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db

app = create_app()

DRY_RUN = "--execute" not in sys.argv


def count_empty_policies():
    result = db.session.execute(
        db.text("SELECT COUNT(*) FROM policies WHERE carrier = 'Humana' AND mbi = ''")
    )
    return result.scalar()


def count_empty_customers():
    result = db.session.execute(
        db.text("SELECT COUNT(*) FROM customers WHERE mbi = ''")
    )
    return result.scalar()


with app.app_context():
    policy_count_before = count_empty_policies()
    customer_count_before = count_empty_customers()

    print("=" * 60)
    print("Humana MBI empty-string → NULL backfill")
    print("=" * 60)
    print(f"  Humana policies with mbi='':  {policy_count_before}")
    print(f"  Customers with mbi='':        {customer_count_before}")
    print()

    if DRY_RUN:
        print("DRY-RUN mode — no changes made.")
        print("Run with --execute to apply the updates.")
        sys.exit(0)

    print("Applying updates...")

    db.session.execute(
        db.text("UPDATE policies SET mbi = NULL WHERE carrier = 'Humana' AND mbi = ''")
    )
    db.session.execute(
        db.text("UPDATE customers SET mbi = NULL WHERE mbi = ''")
    )
    db.session.commit()

    policy_count_after = count_empty_policies()
    customer_count_after = count_empty_customers()

    print(
        f"Updated {policy_count_before} Humana policies, "
        f"{customer_count_before} customers."
    )
    print(
        f"Verification: {policy_count_after}='' policies, "
        f"{customer_count_after}='' customers remaining."
    )

    if policy_count_after == 0 and customer_count_after == 0:
        print("\nAll empty-string MBIs converted to NULL. Safe to run migration 014.")
    else:
        print(
            f"\nWARNING: {policy_count_after} policies and "
            f"{customer_count_after} customers still have mbi=''. "
            "Investigate before running migration 014."
        )
        sys.exit(1)
