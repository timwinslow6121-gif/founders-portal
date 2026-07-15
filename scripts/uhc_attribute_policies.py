"""Attribute the 14 UHC active policies with agent_id=None. Dry-run by default.

Two groups (see uhc_unattributed_diag.py):
  Group 1 (12): customer.primary_agent_id is set (Rebekah, id 4) but the policy's
    agent_id was never populated → backfill policy.agent_id = customer.primary_agent_id.
  Group 2 (2): written by Patricia Hill (BOB agentId 2080465), who has no portal user /
    contract map → attribute to Donald Long (retired, id 18), per the established
    Patricia-Hill → Don-Long rule (Aetna reconciliation, 2026-07-10).

Only Policy.agent_id changes — no money, no identity, no plan change.

Run on the VPS:
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/uhc_attribute_policies.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import Policy, Customer, User

DON_LONG_ID = 18
HILL_CARRIER_ID = "2080465"


def main(apply):
    app = create_app()
    with app.app_context():
        uhc = Policy.query.filter_by(carrier="UHC", status="active", agent_id=None).all()
        print(f"{'APPLY' if apply else 'DRY-RUN'} — attribute {len(uhc)} unattributed UHC policies\n")

        g1 = g2 = skipped = 0
        for p in uhc:
            cust = db.session.get(Customer, p.customer_id) if p.customer_id else None
            # Group 2: Patricia Hill's carrier id -> Don Long
            if (p.agent_id_carrier or "").strip() == HILL_CARRIER_ID:
                who = db.session.get(User, DON_LONG_ID)
                print(f"  G2 pid {p.id} | {cust.full_name if cust else '?'} | "
                      f"Hill ({p.agent_id_carrier}) -> Don Long ({DON_LONG_ID}) {who.name if who else '?'}")
                if apply:
                    p.agent_id = DON_LONG_ID
                g2 += 1
                continue
            # Group 1: backfill from the customer's primary agent
            if cust and cust.primary_agent_id:
                ag = db.session.get(User, cust.primary_agent_id)
                print(f"  G1 pid {p.id} | {cust.full_name} | "
                      f"customer agent {cust.primary_agent_id} ({ag.name if ag else '?'}) -> policy.agent_id")
                if apply:
                    p.agent_id = cust.primary_agent_id
                g1 += 1
                continue
            print(f"  SKIP pid {p.id} | {cust.full_name if cust else '?'} | "
                  f"no customer agent + not Hill (needs manual)")
            skipped += 1

        print(f"\n  Group 1 (customer-agent backfill): {g1}")
        print(f"  Group 2 (Hill -> Don Long): {g2}")
        print(f"  skipped (manual): {skipped}")
        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — no changes written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
