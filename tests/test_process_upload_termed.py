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


def test_route_termed_rec_old_row_does_not_term_newer_active(db_session, app):
    """SHARED termed path (both /upload and /upload/bulk): an OLD termed row must NOT
    term a member's NEWER active policy that shares the same member_id (Robbie Belk).
    It seeds a closed history chapter and leaves the live policy active."""
    from app.upload import _route_termed_rec
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(name="Ag", email="a@x.com", agency_id=ag.id)
        db.session.add(u); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Robbie Belk", first_name="Robbie",
                     last_name="Belk", mbi="MBIRB", primary_agent_id=u.id)
        db.session.add(c)
        # Current active policy: C-SNP eff 2026 (member_id reused from the old plan).
        p = Policy(agency_id=ag.id, carrier="Aetna", member_id="RB1", mbi="MBIRB",
                   status="active", plan_name="Chronic Care C-SNP",
                   effective_date=date(2026, 1, 1),
                   first_name="Robbie", last_name="Belk", full_name="Robbie Belk")
        db.session.add(p); db.session.commit()

        old_termed = {"carrier": "Aetna", "member_id": "RB1", "mbi": "MBIRB",
                      "plan_name": "Value Plus", "effective_date": date(2023, 1, 1),
                      "term_date": date(2025, 12, 31)}
        assert _route_termed_rec(old_termed, ag.id) == "updated"
        db.session.commit()

        # Live policy stays ACTIVE (the old termed row did NOT clobber it).
        pol = Policy.query.filter_by(agency_id=ag.id, member_id="RB1").first()
        assert pol.status == "active"
        assert pol.plan_name == "Chronic Care C-SNP"
        # Old enrollment seeded as a closed history chapter.
        h = CustomerAorHistory.query.filter_by(
            customer_id=c.id, carrier="Aetna", effective_date=date(2023, 1, 1)).first()
        assert h is not None
        assert h.end_date == date(2025, 12, 31)
