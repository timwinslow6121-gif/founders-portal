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
                     city="Kannapolis", county="Cabarrus",
                     created_by_id=uid)
        p.set_carriers(["Humana", "BCBS"])
        db.session.add(p); db.session.commit()
        got = Provider.query.filter_by(name="NE Digestive").first()
        assert got.county == "Cabarrus"
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


def test_provider_new_persists_carriers(ctx):
    app, agency_id, uid = ctx
    from app import providers
    with app.test_request_context("/providers/new", method="POST", data={
            "name": "Kannapolis Family Med", "provider_type": "family",
            "city": "Kannapolis", "county": "Cabarrus",
            "carriers": ["Humana", "UHC"]}):
        _login(app, uid)
        providers.provider_new()
    with app.app_context():
        p = Provider.query.filter_by(name="Kannapolis Family Med").first()
        assert p is not None
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


def test_provider_group_column(ctx):
    app, agency_id, uid = ctx
    with app.app_context():
        p = Provider(agency_id=agency_id, name="Dr. Tuttle", group="Novant",
                     created_by_id=uid)
        db.session.add(p); db.session.commit()
        assert Provider.query.filter_by(name="Dr. Tuttle").first().group == "Novant"


def test_provider_bills_ppo_oon_removed():
    # the whole-provider flag is retired; the column/attr should be gone
    from app.models import Provider
    assert not hasattr(Provider, "bills_ppo_oon") or "bills_ppo_oon" not in Provider.__table__.columns


def test_plan_flag_upsert_and_remove(ctx):
    app, agency_id, uid = ctx
    from app.models import Plan
    with app.app_context():
        pl = Plan(agency_id=agency_id, carrier="Devoted", cms_plan_id="H1234-001",
                  year=2026, plan_name="Devoted Choice (PPO)", plan_type="mapd",
                  plan_subtype="ppo", status="current")
        db.session.add(pl); db.session.flush()
        p = Provider(agency_id=agency_id, name="NE Digestive", county="Cabarrus",
                     created_by_id=uid)
        db.session.add(p); db.session.flush()
        p.set_plan_flag(pl.id, "out_of_network", "no", agency_id)
        db.session.commit()
        flags = p.plan_flags
        assert len(flags) == 1
        assert flags[0]["plan_id"] == pl.id
        assert flags[0]["status"] == "out_of_network"
        assert flags[0]["bills_oon"] == "no"
        # upsert replaces
        p.set_plan_flag(pl.id, "in_network", "yes", agency_id)
        db.session.commit()
        assert len(p.plan_flags) == 1 and p.plan_flags[0]["status"] == "in_network"
        # remove
        p.remove_plan_flag(pl.id); db.session.commit()
        assert p.plan_flags == []
