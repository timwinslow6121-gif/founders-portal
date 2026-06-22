"""Link 4: derive a CustomerAorHistory interval for agent'd customers that have none,
from their policy facts (carrier-provided effective/term dates are authoritative;
BCBS end_date always None). Dry-run default; --apply. Idempotent. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_aor_intervals.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import Customer, Policy, CustomerAorHistory


def derive_interval_for_customer(customer, agency_id):
    if customer.primary_agent_id is None:
        return {"action": "skip", "why": "no agent"}
    # pick the customer's active policy with the facts we need
    pol = (Policy.query.filter_by(customer_id=customer.id, agency_id=agency_id, status="active")
           .filter(Policy.effective_date.isnot(None), Policy.carrier.isnot(None))
           .order_by(Policy.effective_date.asc()).first())
    if pol is None:
        return {"action": "queued", "why": "no policy facts"}
    end = None if pol.carrier == "BCBS" else pol.term_date
    exists = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=pol.carrier,
        effective_date=pol.effective_date).first()
    if exists:
        return {"action": "skip", "why": "interval exists"}
    db.session.add(CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=customer.primary_agent_id,
        carrier=pol.carrier, effective_date=pol.effective_date, end_date=end,
        source="derive_backfill"))
    return {"action": "derived", "carrier": pol.carrier}


def main(apply):
    app = create_app()
    with app.app_context():
        with_agent = Customer.query.filter(Customer.primary_agent_id.isnot(None))
        have_iv = db.session.query(CustomerAorHistory.customer_id).distinct()
        rows = with_agent.filter(~Customer.id.in_(have_iv)).all()
        out = Counter()
        for c in rows:
            out[derive_interval_for_customer(c, c.agency_id)["action"]] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — {len(rows)} customers w/ agent but no interval:")
        for a, n in out.most_common():
            print(f"  {n:5d}  {a}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
