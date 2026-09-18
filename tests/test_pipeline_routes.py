"""Pipeline endpoints: auth, agency scoping, row shape."""
import datetime as dt


def _login(client, uid):
    # flask-login caches the resolved user on `g._login_user` per app context,
    # which pytest keeps alive for the whole test function -- clear it whenever
    # a test logs someone in mid-test (same precedent as tests/test_roadmap.py).
    from flask import g
    g.pop("_login_user", None)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)


def _logout(client):
    from flask import g
    g.pop("_login_user", None)
    with client.session_transaction() as s:
        s.pop("_user_id", None)


def test_pipeline_index_requires_login(client):
    _logout(client)
    r = client.get("/pipeline/")
    assert r.status_code in (302, 401)


def test_today_api_requires_login(client):
    _logout(client)
    r = client.get("/pipeline/api/today")
    assert r.status_code in (302, 401)


def test_customer_row_shape(db_session, app, agency, customer):
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    from app.pipeline.routes import customer_row
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id, shp_end=dt.date(2026, 10, 30))
        ps = PipelineState(agency_id=agency.id, customer_id=customer.id)
        db.session.add_all([cfg, ps])
        db.session.commit()
        row = customer_row(customer, ps, cfg, dt.date(2026, 10, 20))
        for key in ("id", "name", "phone", "stage", "stage_label", "tier",
                    "reason_code", "queue_id", "settled"):
            assert key in row, f"missing {key}"
        assert row["settled"] is False
        assert row["stage_label"] == "Needs a call"


def test_settled_is_true_only_when_done(db_session, app, agency, customer):
    from app.models import PipelineState, PipelineConfig
    from app.extensions import db
    from app.pipeline.routes import customer_row
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id)
        ps = PipelineState(agency_id=agency.id, customer_id=customer.id,
                           stage="done", outcome="kept")
        db.session.add_all([cfg, ps])
        db.session.commit()
        row = customer_row(customer, ps, cfg, dt.date(2026, 10, 20))
        assert row["settled"] is True
        assert row["outcome"] == "kept"


def test_today_excludes_other_agents_and_deceased(db_session, app, client, agency,
                                                  agent_user, customer):
    """Two leaks this endpoint must not have: another agent's book, and the dead.

    Both customers below are put in the `callfirst` queue shape (track=lead with
    an urgent SEP so tier_for returns tier 1, stage=contact, attempts=0) so they
    WOULD appear if the filters were missing -- the mine/alive control proves
    the queue actually fires.
    """
    from app.extensions import db
    from app.models import Customer, User, PipelineState, PipelineConfig
    with app.app_context():
        other = User(email="other@test.com", name="Other Agent",
                     agency_id=agency.id)
        db.session.add(other)
        db.session.commit()

        def _cust(first, agent_id, deceased=None):
            c = Customer(first_name=first, last_name="Row",
                         full_name=f"{first} Row", agency_id=agency.id,
                         primary_agent_id=agent_id, deceased_date=deceased,
                         source="test")
            db.session.add(c)
            db.session.flush()
            db.session.add(PipelineState(
                agency_id=agency.id, customer_id=c.id, track="lead",
                stage="contact", attempts=0,
                sep_end=dt.date.today() + dt.timedelta(days=3)))
            return c

        mine = _cust("Mine", agent_user.id)
        theirs = _cust("Theirs", other.id)
        dead = _cust("Dead", agent_user.id, deceased=dt.date(2026, 1, 1))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
        mine_id, theirs_id, dead_id = mine.id, theirs.id, dead.id

        _login(client, agent_user.id)
        r = client.get("/pipeline/api/today")
        assert r.status_code == 200
        data = r.get_json()

        ids = {row["id"] for card in data["cards"] for row in card["rows"]}
        assert mine_id in ids, "the agent's own live customer must be listed"
        assert theirs_id not in ids, "another agent's customer leaked into /api/today"
        assert dead_id not in ids, "a deceased customer leaked into /api/today"
        # Counters are drawn from the same book and must not count them either.
        assert data["total"] == 1


def test_today_excludes_other_agencies(db_session, app, client, agency,
                                       agent_user, customer):
    """Cross-tenant: a same-named agent's customer in another agency."""
    from app.extensions import db
    from app.models import Agency, Customer, PipelineState, PipelineConfig
    with app.app_context():
        other_agency = Agency(name="Other Agency")
        db.session.add(other_agency)
        db.session.commit()

        # Same primary_agent_id, different agency -- only agency_id separates it.
        foreign = Customer(first_name="Foreign", last_name="Row",
                           full_name="Foreign Row", agency_id=other_agency.id,
                           primary_agent_id=agent_user.id, source="test")
        db.session.add(foreign)
        db.session.flush()
        db.session.add(PipelineState(
            agency_id=other_agency.id, customer_id=foreign.id, track="lead",
            stage="contact", attempts=0,
            sep_end=dt.date.today() + dt.timedelta(days=3)))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
        foreign_id = foreign.id

        _login(client, agent_user.id)
        r = client.get("/pipeline/api/today")
        assert r.status_code == 200
        data = r.get_json()
        ids = {row["id"] for card in data["cards"] for row in card["rows"]}
        assert foreign_id not in ids, "cross-tenant customer leaked into /api/today"
        assert data["total"] == 0
