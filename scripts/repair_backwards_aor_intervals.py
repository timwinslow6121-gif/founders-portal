"""Repair AOR intervals corrupted by the pre-fix BOB termed-row clobber.

The 2026-06-23 Aetna CSV import (before the chronological-dedup fix) let an OLD
termed history row close a member's LIVE AOR interval at the OLD term date. The
signature is a BACKWARDS interval: effective_date > end_date — an interval can never
legitimately end before it starts, so any such row is corruption from that clobber.
Re-importing the CSV does NOT self-heal these (the open-interval dedup guard sees the
interval already exists and won't reopen it), so this one-time cleanup reopens them.

Repair: set end_date = None on every CustomerAorHistory row where
effective_date > end_date (both non-null). This restores the live (newer) interval to
OPEN. Idempotent (a second run finds nothing). Dry-run default; pass --apply to write.

Back up the DB first. Run on VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
    scripts/repair_backwards_aor_intervals.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import CustomerAorHistory, Customer


def find_backwards_intervals():
    """Every interval whose effective_date is strictly after its end_date."""
    return (CustomerAorHistory.query
            .filter(CustomerAorHistory.effective_date.isnot(None),
                    CustomerAorHistory.end_date.isnot(None),
                    CustomerAorHistory.effective_date > CustomerAorHistory.end_date)
            .all())


def main(apply):
    app = create_app()
    with app.app_context():
        rows = find_backwards_intervals()
        if not rows:
            print("No backwards AOR intervals found — nothing to repair.")
            return
        print(f"Found {len(rows)} backwards AOR interval(s) (effective_date > end_date):")
        for iv in rows:
            cust = db.session.get(Customer, iv.customer_id)
            name = cust.full_name if cust else f"customer {iv.customer_id}"
            print(f"  - {name} | {iv.carrier} | {iv.plan_name} | "
                  f"eff {iv.effective_date} -> end {iv.end_date}  =>  reopen (end=None)")
            if apply:
                iv.end_date = None
        if apply:
            db.session.commit()
            print(f"\nAPPLIED: reopened {len(rows)} interval(s).")
        else:
            print(f"\nDRY-RUN: would reopen {len(rows)} interval(s). Re-run with --apply.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
