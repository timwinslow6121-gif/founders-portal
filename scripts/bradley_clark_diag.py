"""Read-only: show Bradley (1635) + Clark (1641) full policy + AOR state."""
from app import create_app
from app.models import Customer, Policy, CustomerAorHistory, User


def main():
    app = create_app()
    with app.app_context():
        for cid in (1635, 1641):
            c = Customer.query.get(cid)
            print(f"\n=== cust {cid} | {c.full_name} | dob {c.dob} | mbi {c.mbi} | "
                  f"agent {c.primary_agent.name if c.primary_agent else None} ===")
            pols = Policy.query.filter_by(customer_id=cid).all()
            for p in pols:
                print(f"   policy {p.id} | {p.carrier} | {p.plan_name!r} [{p.plan_type}] | "
                      f"member_id {p.member_id} | status {p.status} | "
                      f"eff {p.effective_date} | term {p.term_date} | agent_id {p.agent_id}")
            aors = CustomerAorHistory.query.filter_by(customer_id=cid).all()
            print(f"   AOR chapters: {len(aors)}")
            for a in aors:
                print(f"     {a.carrier} | {a.effective_date} – {a.end_date} | agent_id {a.agent_id}")


if __name__ == "__main__":
    main()
