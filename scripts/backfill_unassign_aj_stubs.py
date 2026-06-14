"""Re-NULL commission-import stub customers wrongly assigned to the uploading admin.

The commission upload used to default unresolved rows' agent to the UPLOADER (AJ,
who has 0 contracts). That made AJ the primary_agent_id of ~463 stub customers +
created phantom AOR/policy rows under him. This backfill sets those customers to
UNASSIGNED (primary_agent_id NULL) and removes the phantom AOR rows + re-NULLs the
phantom policy agent_id, so they surface in the new 'unassigned' view.

Scope guard: ONLY customers that are stub=True, source='commission_import', and
primary_agent_id = the admin's id. AJ has no contracts, so none are legitimately
his. Idempotent. Pass --apply to write; default is a dry run.

Run on VPS:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_unassign_aj_stubs.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.models import User, Customer, CustomerAorHistory, Policy

APPLY = "--apply" in sys.argv


def main():
    app = create_app()
    with app.app_context():
        admin = User.query.filter(User.email.ilike("%admin@foundersinsuranceagency.com%")).first()
        if not admin:
            print("No admin@ user found — aborting."); return
        print(f"Admin (uploader) = id {admin.id} {admin.name}")

        stubs = Customer.query.filter_by(
            stub=True, source="commission_import", primary_agent_id=admin.id).all()
        print(f"Mis-assigned commission stubs: {len(stubs)}")

        cust_ids = [c.id for c in stubs]
        aor = CustomerAorHistory.query.filter(
            CustomerAorHistory.customer_id.in_(cust_ids),
            CustomerAorHistory.agent_id == admin.id).all() if cust_ids else []
        pol = Policy.query.filter(
            Policy.customer_id.in_(cust_ids),
            Policy.agent_id == admin.id).all() if cust_ids else []
        print(f"  phantom AOR rows under AJ for these customers: {len(aor)}")
        print(f"  phantom policies under AJ for these customers: {len(pol)}")

        if not APPLY:
            print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
            for c in stubs[:5]:
                print(f"   would unassign: customer {c.id} {c.full_name!r}")
            return

        for c in stubs:
            c.primary_agent_id = None
        for a in aor:
            db.session.delete(a)          # AOR requires an agent; an unassigned customer has none
        for p in pol:
            p.agent_id = None             # policy.agent_id is nullable
        db.session.commit()
        print(f"\nAPPLIED: {len(stubs)} customers unassigned, {len(aor)} AOR rows deleted, "
              f"{len(pol)} policies un-attributed.")


if __name__ == "__main__":
    main()
