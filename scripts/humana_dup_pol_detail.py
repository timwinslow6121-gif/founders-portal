"""READ-ONLY: show the 2 active Humana policies per merged keeper (2024
numeric-PID commission-side vs 2026 BOB-side), with payments, to inform the dedup."""
from app import create_app
from app.extensions import db
from app.models import Policy, PolicyPayment, Customer

KEEPERS = [7154, 7623, 6343, 7110, 6958, 7076, 7865, 6963, 7463, 7093, 7520, 7363, 6728]


def main():
    app = create_app()
    with app.app_context():
        for k in KEEPERS:
            pols = (Policy.query.filter_by(customer_id=k, carrier="Humana", status="active")
                    .order_by(Policy.effective_date).all())
            c = db.session.get(Customer, k)
            print("--- %s (cust %s) : %d active Humana ---" % ((c.full_name if c else k), k, len(pols)))
            for p in pols:
                pp = PolicyPayment.query.filter_by(policy_id=p.id).count()
                ppsum = (db.session.query(db.func.coalesce(db.func.sum(PolicyPayment.paid_amount), 0))
                         .filter_by(policy_id=p.id).scalar())
                kind = "numeric-PID" if str(p.member_id).isdigit() else "Humana-ID"
                print("   pol %-6s eff=%s plan=%r plan_id=%s member_id=%r [%s] payments=%d ($%.2f)"
                      % (p.id, p.effective_date, p.plan_name, p.plan_id, p.member_id, kind, pp, float(ppsum)))


if __name__ == "__main__":
    main()
