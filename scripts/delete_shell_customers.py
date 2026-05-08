"""
scripts/delete_shell_customers.py

One-time hard delete of shell customers: records with no MBI, no humana_id,
and no dependents (notes, contacts, AOR history).

Background: Old BOB upload code paths created "shell" customer records for
rows where no MBI could be resolved. These shells have no patient identity
(mbi IS NULL, humana_id IS NULL) and no real data attached. They pollute
the customer table and will interfere with Plan 04-03 duplicate detection.

Note on agency scoping: This script deletes across all agencies because the
dependent checks use customer_id which is unique across the entire table.
Agency scoping on the shell query is not required — shell customers have no
MBI to cross-tenant leak, and the per-row dependent check is agency-agnostic
by design (customer_id FK is globally unique).

Per Phase 04 Plan 04-02 (D-05, D-06, D-21):
  - D-05: Hard delete shells directly — no report-first step needed.
  - D-06: Verify zero dependents (notes, contacts, AOR history) before deleting.
           Any row with dependents is SKIPPED and reported.
  - D-21: Deletion reserved for verified scenarios only.

IMPORTANT: Policy has no customer_id FK — do NOT check Policy table for
           dependents. Policies join customers by MBI; a shell with mbi=NULL
           has no linked policies by definition.

Usage (on VPS):
    cd /var/www/founders-portal

    # Dry-run (default) — shows what would be deleted, makes no changes:
    ./venv/bin/python3 scripts/delete_shell_customers.py

    # Apply deletions:
    ./venv/bin/python3 scripts/delete_shell_customers.py --execute
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import (
    Customer, CustomerNote, CustomerContact, CustomerAorHistory
)


def main():
    execute = "--execute" in sys.argv
    app = create_app()
    with app.app_context():
        shells = Customer.query.filter(
            Customer.mbi.is_(None),
            Customer.humana_id.is_(None),
        ).all()

        print(f"Found {len(shells)} candidate shell customers (mbi=NULL AND humana_id=NULL)")
        print(f"Mode: {'EXECUTE' if execute else 'DRY-RUN'}")
        print("-" * 70)

        deletable = []
        skipped = []

        for c in shells:
            has_notes = (
                db.session.query(CustomerNote.id)
                .filter_by(customer_id=c.id)
                .first() is not None
            )
            has_contacts = (
                db.session.query(CustomerContact.id)
                .filter_by(customer_id=c.id)
                .first() is not None
            )
            has_aor = (
                db.session.query(CustomerAorHistory.id)
                .filter_by(customer_id=c.id)
                .first() is not None
            )

            reasons = []
            if has_notes:
                reasons.append("notes")
            if has_contacts:
                reasons.append("contacts")
            if has_aor:
                reasons.append("aor_history")

            row_label = (
                f"id={c.id} agency={c.agency_id} "
                f"name={c.first_name!r} {c.last_name!r}"
            )

            if reasons:
                skipped.append((c, reasons))
                print(f"  SKIP {row_label} — has {', '.join(reasons)}")
            else:
                deletable.append(c)
                print(f"  DEL  {row_label}")

        print("-" * 70)
        print(f"Deletable: {len(deletable)}")
        print(f"Skipped (has dependents): {len(skipped)}")

        if execute and deletable:
            for c in deletable:
                db.session.delete(c)
            db.session.commit()
            print(f"\nDELETED {len(deletable)} shell customers.")
        elif execute:
            print("\nNothing to delete.")
        else:
            print("\nDRY-RUN — no changes made. Re-run with --execute to apply.")


if __name__ == "__main__":
    main()
