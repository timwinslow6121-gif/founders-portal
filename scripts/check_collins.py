from app import create_app
from app.extensions import db
from app.models import Customer, Policy, CustomerAorHistory, User

app = create_app()
with app.app_context():
    for cid in (2365, 6680):
        c = db.session.get(Customer, cid)
        agent = db.session.get(User, c.primary_agent_id) if c.primary_agent_id else None
        print("cust %s %r dob=%s mbi=%r stub=%s primary_agent=%s (%s)"
              % (cid, c.full_name, c.dob, c.mbi, c.stub, c.primary_agent_id,
                 agent.name if agent else None))
        for p in Policy.query.filter_by(customer_id=cid).all():
            print("   [%s] %s plan=%r type=%s eff=%s"
                  % (p.status, p.carrier, p.plan_name, p.plan_type, p.effective_date))
        for h in CustomerAorHistory.query.filter_by(customer_id=cid).all():
            ag = db.session.get(User, h.agent_id) if h.agent_id else None
            print("   AOR %s agent=%s (%s) eff=%s end=%s"
                  % (h.carrier, h.agent_id, (ag.name if ag else None), h.effective_date, h.end_date))
    print()
    for u in User.query.all():
        if u.name and "chris" in u.name.lower():
            print("Chris =", u.id, u.name)
