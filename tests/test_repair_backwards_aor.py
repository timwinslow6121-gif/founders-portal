"""The one-time repair for AOR intervals corrupted by the pre-fix BOB termed-row
clobber: a backwards interval (effective_date > end_date) must be detected and
reopened (end_date=None); a normal closed interval must be left alone."""
from datetime import date
from app.extensions import db
from app.models import Agency, User, Customer, CustomerAorHistory
from scripts.repair_backwards_aor_intervals import find_backwards_intervals


def _mk(app):
    ag = Agency(name="T"); db.session.add(ag); db.session.flush()
    u = User(name="A", email="a@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
    c = Customer(agency_id=ag.id, first_name="Rob", last_name="Belk",
                 full_name="Rob Belk", primary_agent_id=u.id)
    db.session.add(c); db.session.flush()
    return ag, u, c


def test_finds_and_reopens_backwards_interval(db_session, app):
    with app.app_context():
        ag, u, c = _mk(app)
        # The clobber signature: live 2026 interval wrongly closed at 2025-12-31.
        bad = CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="C-SNP",
            effective_date=date(2026, 1, 1), end_date=date(2025, 12, 31))
        db.session.add(bad); db.session.commit()

        found = find_backwards_intervals()
        assert len(found) == 1 and found[0].id == bad.id

        # Apply the repair (mirrors the script's --apply branch).
        for iv in found:
            iv.end_date = None
        db.session.commit()
        assert db.session.get(CustomerAorHistory, bad.id).end_date is None
        # Idempotent: a second pass finds nothing.
        assert find_backwards_intervals() == []


def test_leaves_normal_closed_interval_alone(db_session, app):
    with app.app_context():
        ag, u, c = _mk(app)
        good = CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="Value Plus",
            effective_date=date(2023, 1, 1), end_date=date(2025, 12, 31))  # eff < end: fine
        opn = CustomerAorHistory(agency_id=ag.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", plan_name="C-SNP",
            effective_date=date(2026, 1, 1), end_date=None)               # open: fine
        db.session.add_all([good, opn]); db.session.commit()
        assert find_backwards_intervals() == []
