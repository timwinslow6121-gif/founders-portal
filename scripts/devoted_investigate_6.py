"""READ-ONLY: investigate the 6 DB-active-Devoted-not-in-BOB members.
For each, dump their full policy set across ALL carriers + whether they have a
NEWER active enrollment elsewhere (the switcher signal). Writes nothing."""
from app import create_app
from app.extensions import db
from app.models import Policy, Customer

MBIS = ["1A60NT3JV31", "1X57MJ7FA64", "4N00NU4TE02",
        "5QV6UJ7TN55", "5U63VX3HJ72", "6C64U80TF09"]


def main():
    app = create_app()
    with app.app_context():
        for mbi in MBIS:
            c = Customer.query.filter(Customer.mbi == mbi).first()
            if not c:
                print("MBI", mbi, "-> no customer"); continue
            print("=" * 70)
            print("%s  mbi=%s dob=%s agent=%s addr=%r %s %s" %
                  (c.full_name, c.mbi, c.dob, c.primary_agent_id,
                   c.address1, c.city, c.zip_code))
            pols = Policy.query.filter_by(customer_id=c.id).order_by(
                Policy.effective_date.desc().nullslast()).all()
            for p in pols:
                print("    [%s] %-9s mid=%-14r plan=%r type=%s eff=%s term=%s" %
                      (p.status, p.carrier, p.member_id, p.plan_name,
                       p.plan_type, p.effective_date, p.term_date))
            # also: any OTHER customer record sharing this dob+name (dup)?
            if c.dob:
                twins = (Customer.query
                         .filter(Customer.id != c.id, Customer.dob == c.dob)
                         .all())
                same_name = [t for t in twins
                             if (t.full_name or "").lower() == (c.full_name or "").lower()]
                if same_name:
                    print("    !! same name+dob other record(s):",
                          [(t.id, t.mbi) for t in same_name])


if __name__ == "__main__":
    main()
