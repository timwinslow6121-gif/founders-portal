"""READ-ONLY: list every line item whose stored split_rate disagrees with the
agent's contract for that carrier.

Run before and after deploying the edit-form guard. Known-legitimate rows will
still appear -- Anjana Patel keeps 100% on non-Cannon-Pharmacy customers and
Betty Marlowe is paid a flat $100/application plus hourly direct from Brian --
so this is a REVIEW list, not a defect list. See BACKLOG.md 'split_rate=1.0 is
an OVERLOADED marker'.

    ./venv/bin/python3 scripts/check_off_contract_rows.py
"""
import sys
from collections import defaultdict

from app import create_app
from app.models import CommissionLineItem, CommissionStatement, User
from app.commission.recap import contract_rate_for
from app.commission.ledger import split_breakdown


def main():
    app = create_app()
    with app.app_context():
        # User.name is nullable; fall back so a NULL name cannot TypeError on the
        # `nm[:20]` slice partway through the report.
        users = {u.id: (u.name or u.email or "(agent %s)" % u.id)
                 for u in User.query.all()}
        cache = {}
        groups = defaultdict(lambda: {"n": 0, "delta": 0.0})
        for li in CommissionLineItem.query.filter(
                CommissionLineItem.agent_id.isnot(None),
                CommissionLineItem.split_rate.isnot(None)).all():
            rate = contract_rate_for(li.agent_id, li.carrier, li.agency_id, cache)
            if rate is None or abs((li.split_rate or 0) - rate) <= 0.0005:
                continue
            st = CommissionStatement.query.get(li.statement_id)
            paid, _ = split_breakdown(li)
            should = (li.raw_amount or 0) * rate
            key = (li.carrier, st.period_label if st else "?",
                   users.get(li.agent_id, "?"), li.split_rate, rate)
            groups[key]["n"] += 1
            groups[key]["delta"] += (paid - should)

        if not groups:
            print("No rows disagree with their agent's contract rate.")
            return 0
        print("%-10s %-13s %-20s %7s %8s %5s %10s"
              % ("carrier", "period", "agent", "stored", "contract", "rows", "delta"))
        total = 0.0
        for key in sorted(groups, key=lambda k: -abs(groups[k]["delta"])):
            car, per, nm, stored, rate = key
            d = groups[key]
            total += d["delta"]
            print("%-10s %-13s %-20s %7s %8s %5d %10.2f"
                  % (car, per, nm[:20], stored, rate, d["n"], d["delta"]))
        print("%-58s %10.2f" % ("TOTAL (review, not all errors)", total))
        return 0


if __name__ == "__main__":
    sys.exit(main())
