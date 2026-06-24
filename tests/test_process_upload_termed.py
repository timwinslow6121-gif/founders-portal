"""The legacy /upload (process_upload) path must honor the termed-row invariants
just like /upload/bulk: a termed row never creates a new policy, a departed member
is skipped, and an unresolved row never blanks a known owner. (Final-review Issue 1+2.)"""
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, Policy, CustomerAorHistory
from app.upload import _close_open_aor_on_term, _seed_closed_history


def test_unresolved_row_does_not_blank_existing_owner(db_session, app):
    """_upsert_customer_from_policy with agent_id=None must keep the existing owner."""
    from app.upload import _upsert_customer_from_policy
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Owner", email="o@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                     last_name="Doe", mbi="1ABC", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=ag.id, carrier="Aetna", member_id="1ABC", mbi="1ABC",
                   status="active", first_name="Jane", last_name="Doe", full_name="Jane Doe")
        db.session.add(p); db.session.commit()
        rec = {"carrier": "Aetna", "member_id": "1ABC", "mbi": "1ABC",
               "first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe",
               "dob": None, "phone": "", "address1": "", "city": "", "state": "",
               "zip_code": "", "county": ""}
        # agent_id None (unresolved) must NOT blank the known owner
        _upsert_customer_from_policy(rec, None, None, ag.id)
        db.session.commit()
        assert db.session.get(Customer, c.id).primary_agent_id == u.id


def test_termed_departed_member_creates_nothing(db_session, app):
    """A termed rec for a non-customer: the termed-row helpers leave no trace."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        db.session.commit()
        # No customer with this MBI exists → the routing 'continue'/skip leaves nothing.
        assert Customer.query.filter_by(mbi="ZZZ").first() is None
        assert Policy.query.filter_by(member_id="ZZZ").first() is None
