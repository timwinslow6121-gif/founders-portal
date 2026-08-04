import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, User, Provider


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        u = User(email="a@foundersinsuranceagency.com", name="A", is_admin=True,
                 agency_id=ag.id, role="admin")
        db.session.add(u); db.session.commit()
        yield app, ag.id, u.id
        db.session.remove(); db.drop_all()


def test_provider_persists_with_carriers(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="NE Digestive", provider_type="gastro",
                     city="Kannapolis", county="Cabarrus", bills_ppo_oon="no",
                     created_by_id=uid)
        p.set_carriers(["Humana", "BCBS"])
        db.session.add(p); db.session.commit()
        got = Provider.query.filter_by(name="NE Digestive").first()
        assert got.county == "Cabarrus"
        assert got.bills_ppo_oon == "no"
        assert set(got.carrier_names) == {"Humana", "BCBS"}


def test_provider_set_carriers_replaces(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        p.set_carriers(["Humana"]); db.session.add(p); db.session.commit()
        p.set_carriers(["UHC", "Aetna"]); db.session.commit()
        assert set(p.carrier_names) == {"UHC", "Aetna"}   # replaced, not appended


def _login(app, uid):
    from flask_login import login_user
    from app.models import User
    login_user(db.session.get(User, uid))


def test_provider_list_renders_grouped(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus",
                     created_by_id=uid); p.set_carriers(["Humana"])
        db.session.add(p); db.session.commit()
    client = app.test_client()
    with app.test_request_context():
        _login(app, uid)
    # LOGIN_DISABLED=True → current_user is a dummy; call the view directly instead:
    from app import providers
    with app.test_request_context("/providers"):
        _login(app, uid)
        resp = providers.provider_list()
    html = resp if isinstance(resp, str) else resp.get_data(as_text=True)
    assert "NE Digestive" in html
    assert "Cabarrus" in html


def test_provider_new_persists_carriers_and_flag(ctx):
    app, agency_id, uid = ctx
    from app import providers
    with app.test_request_context("/providers/new", method="POST", data={
            "name": "Kannapolis Family Med", "provider_type": "family",
            "city": "Kannapolis", "county": "Cabarrus", "bills_ppo_oon": "yes",
            "carriers": ["Humana", "UHC"]}):
        _login(app, uid)
        providers.provider_new()
    with app.app_context():
        p = Provider.query.filter_by(name="Kannapolis Family Med").first()
        assert p is not None
        assert p.bills_ppo_oon == "yes"
        assert set(p.carrier_names) == {"Humana", "UHC"}


def test_provider_edit_blocked_for_non_editor(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        # a plain agent (not senior/admin) — can_edit_shared_data False
        from app.models import User
        agent = User(email="agent@foundersinsuranceagency.com", name="Ag",
                     is_admin=False, agency_id=agency_id, role="agent")
        db.session.add(agent); db.session.flush()
        p = Provider(agency_id=agency_id, name="X", created_by_id=uid)
        db.session.add(p); db.session.commit()
        agent_id, pid = agent.id, p.id
    from app import providers
    from werkzeug.exceptions import Forbidden
    with app.test_request_context(f"/providers/{pid}/edit", method="POST",
                                  data={"name": "Y"}):
        _login(app, agent_id)
        with pytest.raises(Forbidden):
            providers.provider_edit(pid)
