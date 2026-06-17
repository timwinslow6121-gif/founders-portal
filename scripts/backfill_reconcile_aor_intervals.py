"""
scripts/backfill_reconcile_aor_intervals.py

Phase 1 AOR reconciliation backfill. Closes superseded OPEN intervals created
before the resolver learned to supersede (the Tocara Brown duplicate-open bug):
when a customer has >1 OPEN interval for the same carrier, every interval that is
strictly earlier than a later open interval is end-dated, leaving exactly one
(the newest) open per carrier.

Close boundary mirrors the live resolver (Tim's §7): the superseded interval is
closed the day before the next interval's effective date (Medicare effs are the
1st, so next_eff-1 lands on month-end, e.g. 6/1 -> 5/31). BCBS is excluded — its
end_date is a renewal date, never a termination.

Idempotent (a second run finds nothing left to close). Dry-run by default.

Run on VPS:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
                 scripts/backfill_reconcile_aor_intervals.py [--apply]
"""
import os
import sys
from collections import defaultdict
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Customer, CustomerAorHistory

def reconcile_open_intervals(verbose=True):
    """Close superseded OPEN intervals in-place (no commit). Returns (groups_touched,
    closed_count). Mirrors the live resolver's supersession rule so script and
    resolver can't drift. BCBS excluded — its end_date is a renewal date."""
    open_rows = (
        CustomerAorHistory.query
        .filter(CustomerAorHistory.end_date.is_(None))
        .filter(CustomerAorHistory.carrier != "BCBS")
        .all()
    )

    groups = defaultdict(list)
    for row in open_rows:
        groups[(row.customer_id, row.carrier)].append(row)

    closed = 0
    groups_touched = 0

    for (customer_id, carrier), rows in groups.items():
        # Only groups with a real duplication (>=2 open) AND with usable eff dates.
        dated = [r for r in rows if r.effective_date is not None]
        if len(dated) < 2:
            continue

        # Newest effective date stays open; every strictly-earlier open interval is
        # superseded, closed the day before the NEXT interval's effective date.
        dated.sort(key=lambda r: r.effective_date)
        newest_eff = dated[-1].effective_date
        group_closed = False

        for i, row in enumerate(dated[:-1]):
            next_eff = dated[i + 1].effective_date
            if row.effective_date >= newest_eff:
                continue  # defensive: never close the newest
            close_date = next_eff - timedelta(days=1)
            if verbose:
                customer = Customer.query.get(customer_id)
                cname = customer.full_name if customer else "?"
                print(
                    f"  Close AOR {row.id}: cust={customer_id} ({cname}) carrier={carrier} "
                    f"eff={row.effective_date} -> end={close_date} "
                    f"(superseded by eff={next_eff})"
                )
            row.end_date = close_date
            closed += 1
            group_closed = True

        if group_closed:
            groups_touched += 1

    return groups_touched, closed


if __name__ == "__main__":
    APPLY = "--apply" in sys.argv
    app = create_app()
    with app.app_context():
        groups_touched, closed = reconcile_open_intervals(verbose=True)
        print(
            f"\n{groups_touched} (customer,carrier) groups with duplicate open intervals; "
            f"{closed} interval(s) to close."
        )
        if APPLY:
            db.session.commit()
            print("APPLIED — changes committed.")
        else:
            db.session.rollback()
            print("DRY RUN — nothing written. Re-run with --apply to commit.")
