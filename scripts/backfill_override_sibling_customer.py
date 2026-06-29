"""
Backfill customer_id onto orphaned Founders-override `::ovr` sibling line items.

Quirk #4: edit_line_split + resolve_quarantine_line used to create the override
sibling WITHOUT copying the parent's customer_id, so every AJ edit/resolve spawned a
line item with customer_id=NULL (the radar's payment_without_customer regression).
The code is now fixed; this one-time backfill repairs the existing orphans by copying
the PARENT line's customer_id onto the sibling.

- A sibling's parent = same statement_id, source_ref = sibling's source_ref minus
  the trailing "::ovr".
- Only siblings whose PARENT has a customer_id are fixable; if the parent is also
  customer-less, the sibling stays NULL (separate pre-existing no-MBI debt, not this bug).
- Dry-run by default; --apply commits. Idempotent. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_override_sibling_customer.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem


def main(apply: bool):
    app = create_app()
    with app.app_context():
        orphans = (CommissionLineItem.query
                   .filter(CommissionLineItem.customer_id.is_(None),
                           CommissionLineItem.source_ref.like("%::ovr"))
                   .all())
        fixable = 0
        parent_also_null = 0
        no_parent = 0
        for ovr in orphans:
            parent_ref = ovr.source_ref[:-len("::ovr")]
            parent = (CommissionLineItem.query
                      .filter_by(statement_id=ovr.statement_id, source_ref=parent_ref)
                      .first())
            if parent is None:
                no_parent += 1
                continue
            if parent.customer_id is None:
                parent_also_null += 1
                continue
            print(f"  fix ovr id={ovr.id} ({ovr.carrier} {ovr.member_name}) "
                  f"customer_id NULL -> {parent.customer_id}")
            ovr.customer_id = parent.customer_id
            fixable += 1

        print(f"\norphaned ::ovr siblings (customer_id NULL): {len(orphans)}")
        print(f"  fixable (parent has a customer):    {fixable}")
        print(f"  parent also customer-less (skip):   {parent_also_null}")
        print(f"  no parent found (skip):             {no_parent}")

        if apply:
            db.session.commit()
            print("\nAPPLIED — committed.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing committed. Re-run with --apply to commit.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
