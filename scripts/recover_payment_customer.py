# scripts/recover_payment_customer.py
"""Link 1: re-point NULL-customer commission line items to real customers via the
identity ladder (MBI -> carrier_member_id -> composite). Deletes any uhc::N stub
policy whose payment now links. Dry-run default; --apply commits. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_payment_customer.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import CommissionLineItem, Policy
from app.identity import resolve_payment_identity

def main(apply):
    app = create_app()
    with app.app_context():
        rows = (CommissionLineItem.query
                .filter(CommissionLineItem.customer_id.is_(None),
                        CommissionLineItem.classification.in_(["agent_commission", "chargeback"]))
                .all())
        tiers = Counter(); queued = 0; stubs_deleted = 0
        for li in rows:
            r = resolve_payment_identity(li, li.agency_id)
            if r["action"] == "linked":
                tiers[r["tier"]] += 1
                if apply and r["delete_stub_policy_id"]:
                    p = db.session.get(Policy, r["delete_stub_policy_id"])
                    if p:
                        db.session.delete(p); stubs_deleted += 1
            else:
                queued += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — linked {sum(tiers.values())} payments:")
        for t, n in tiers.most_common():
            print(f"  {n:5d}  via {t}")
        print(f"  stub policies deleted: {stubs_deleted}")
        print(f"  queued (weak identity → hub): {queued}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
