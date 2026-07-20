"""Read-only: full state of the Milton Frazier + Lukisha Truesdale clusters."""
from app import create_app
from app.models import Customer, Policy, CustomerAorHistory


def show(name):
    custs = Customer.query.filter(Customer.full_name == name).all()
    print(f"\n=== {name} — {len(custs)} records ===")
    for c in custs:
        print(f"  cust {c.id} | dob {c.dob} | mbi {c.mbi} | humana_id {c.humana_id} | "
              f"agent {c.primary_agent.name if c.primary_agent else None} | "
              f"stub={c.stub} | phone {c.phone_primary!r} | addr {c.address1!r} {c.city!r} {c.state!r} {c.zip_code!r}")
        pols = Policy.query.filter_by(customer_id=c.id).all()
        for p in pols:
            print(f"      policy {p.id} | {p.carrier} | {p.plan_name!r} | member_id {p.member_id} | "
                  f"mbi {p.mbi} | status {p.status} | eff {p.effective_date}")
        aors = CustomerAorHistory.query.filter_by(customer_id=c.id).all()
        for a in aors:
            print(f"      AOR | {a.carrier} | {a.effective_date} – {a.end_date}")


def main():
    app = create_app()
    with app.app_context():
        show("Milton Frazier")
        show("Lukisha Truesdale")


if __name__ == "__main__":
    main()
