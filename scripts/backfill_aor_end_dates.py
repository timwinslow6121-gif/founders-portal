"""
scripts/backfill_aor_end_dates.py

One-time backfill: for any customer whose primary_agent_id differs from
the agent on their most recent open AOR history row (end_date IS NULL),
close that row by setting end_date to today.

This fixes historical data created before the upload.py AOR-transfer
detection was added. Run once after deploying the AOR visibility feature.

Usage (on VPS):
    cd /var/www/founders-portal
    ./venv/bin/python scripts/backfill_aor_end_dates.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app import create_app
from app.extensions import db
from app.models import Customer, CustomerAorHistory

app = create_app()

with app.app_context():
    today = date.today()
    closed = 0
    skipped = 0

    # Find all customers who have at least one open AOR row
    open_rows = (
        CustomerAorHistory.query
        .filter(CustomerAorHistory.end_date.is_(None))
        .all()
    )

    print(f"Found {len(open_rows)} open AOR rows to evaluate...")

    for row in open_rows:
        customer = Customer.query.get(row.customer_id)
        if customer is None:
            skipped += 1
            continue

        # If this row's agent is NOT the current primary agent, close it
        if customer.primary_agent_id and customer.primary_agent_id != row.agent_id:
            row.end_date = today
            closed += 1
            print(
                f"  Closing AOR row {row.id}: customer={row.customer_id} "
                f"agent={row.agent_id} carrier={row.carrier} "
                f"(current AOR is agent {customer.primary_agent_id})"
            )

    db.session.commit()
    print(f"\nDone. Closed {closed} stale AOR rows. Skipped {skipped} (customer not found).")
    print(f"Agents with former customers will now appear in the 'Show former customers' toggle.")
