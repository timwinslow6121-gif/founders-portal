"""Assign unassigned commission-import stub customers from their commission
line-item agent (one-time repair for stubs created before normalize_uhc resolved
the writing agent by Writing Agent ID).

A re-upload does NOT overwrite an existing customer's primary_agent_id (crosswalk
reuse is intentionally non-destructive), so customers created unassigned stay
unassigned. This backfill sets primary_agent_id from the agent we DID resolve on
the customer's commission line item (matched by MBI), and opens the AOR interval
that was skipped at import. Idempotent; --apply to write (dry-run by default).

Run on VPS:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_assign_from_lineitem.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import User, Customer, CommissionLineItem, CustomerAorHistory, Policy

APPLY = "--apply" in sys.argv


def _lineitem_agent(customer):
    """The agent resolved on this customer's commission line item (by MBI)."""
    if not customer.mbi:
        return None
    li = (CommissionLineItem.query
          .filter_by(agency_id=customer.agency_id, mbi=customer.mbi)
          .filter(CommissionLineItem.agent_id.isnot(None))
          .first())
    return li.agent_id if li else None


def main():
    app = create_app()
    with app.app_context():
        unassigned = Customer.query.filter_by(
            stub=True, source="commission_import", primary_agent_id=None).all()
        print(f"Unassigned commission stubs: {len(unassigned)}")

        assigned, no_hint, aor_opened = 0, 0, 0
        from collections import Counter
        by_agent = Counter()
        u = {x.id: x.name for x in User.query.all()}

        for c in unassigned:
            aid = _lineitem_agent(c)
            if not aid:
                no_hint += 1
                continue
            by_agent[u.get(aid, aid)] += 1
            assigned += 1
            if APPLY:
                c.primary_agent_id = aid
                # Open the AOR interval skipped at import: use the customer's policy
                # (carrier/effective) when present, so the book reflects it.
                pol = Policy.query.filter_by(customer_id=c.id).first()
                if pol and pol.effective_date and pol.carrier:
                    exists = CustomerAorHistory.query.filter_by(
                        customer_id=c.id, carrier=pol.carrier,
                        effective_date=pol.effective_date).first()
                    if not exists:
                        db.session.add(CustomerAorHistory(
                            agency_id=c.agency_id, customer_id=c.id, agent_id=aid,
                            carrier=pol.carrier, effective_date=pol.effective_date,
                            end_date=(None if pol.carrier == "BCBS" else pol.term_date),
                            source="commission_import"))
                        aor_opened += 1

        print("Would assign by agent:" if not APPLY else "Assigned by agent:")
        for a, n in by_agent.most_common():
            print(f"  {a:<20} {n}")
        print(f"  no line-item hint (left unassigned): {no_hint}")
        if APPLY:
            db.session.commit()
            print(f"APPLIED: {assigned} customers assigned, {aor_opened} AOR intervals opened.")
        else:
            print(f"\nDRY RUN — {assigned} would be assigned. Re-run with --apply.")


if __name__ == "__main__":
    main()
