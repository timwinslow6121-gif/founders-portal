"""Propagate Policy.agent_id -> Customer.primary_agent_id for unassigned customers.

After the attribution backfill set Policy.agent_id, ~2,795 customers still showed
primary_agent_id=NULL even though they have an attributed active policy. This copies
the agent from the customer's own active policy onto the customer.

SAFETY:
- Only touches customers with primary_agent_id IS NULL.
- Only assigns when ALL of the customer's active, attributed policies point to the
  SAME agent (a customer whose active policies span multiple agents is left for
  manual review — never guessed).
- NEVER overwrites a manually_edited customer's agent (defensive even though we only
  touch NULL primary_agent_id).
- Dry-run by default; --apply commits. Idempotent. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_customer_agent_from_policy.py [--apply]
"""
import sys
from collections import Counter, defaultdict
from app import create_app
from app.extensions import db
from app.models import Customer, Policy, User


def main(apply):
    app = create_app()
    with app.app_context():
        # Map customer_id -> set of agent_ids across its active, attributed policies.
        rows = (db.session.query(Policy.customer_id, Policy.agent_id)
                .filter(Policy.status == "active",
                        Policy.agent_id.isnot(None),
                        Policy.customer_id.isnot(None))
                .distinct().all())
        agents_by_customer = defaultdict(set)
        for cid, aid in rows:
            agents_by_customer[cid].add(aid)

        assigned = Counter()
        skipped_multi = 0
        skipped_manual = 0
        for cust in Customer.query.filter(Customer.primary_agent_id.is_(None)).all():
            agent_ids = agents_by_customer.get(cust.id)
            if not agent_ids:
                continue  # no attributed active policy → stays unassigned
            if cust.manually_edited:
                skipped_manual += 1
                continue
            if len(agent_ids) != 1:
                skipped_multi += 1
                continue  # active policies disagree on the agent → leave for review
            aid = next(iter(agent_ids))
            assigned[aid] += 1
            if apply:
                cust.primary_agent_id = aid
        if apply:
            db.session.commit()

        print(f"{'APPLIED' if apply else 'DRY-RUN'} — assigned {sum(assigned.values())} customers:")
        for aid, n in assigned.most_common():
            u = db.session.get(User, aid)
            print(f"  {n:5d}  {u.name if u else aid}")
        print(f"Skipped (active policies span multiple agents → manual review): {skipped_multi}")
        print(f"Skipped (customer manually_edited): {skipped_manual}")


if __name__ == "__main__":
    main("--apply" in sys.argv)
