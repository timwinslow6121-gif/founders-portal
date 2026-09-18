"""Write endpoints and the gates the server enforces (SPEC 7.4)."""
import pytest


@pytest.fixture
def logged_in(client, app, agency, agent_user, customer, db_session):
    from app.models import Customer, PipelineState, PipelineConfig
    from app.extensions import db
    with app.app_context():
        # The conftest `customer` fixture is DETACHED -- mutating it writes
        # nothing. Re-attach through the live session first.
        c = db.session.get(Customer, customer.id)
        c.primary_agent_id = agent_user.id
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(agent_user.id)
        sess["_fresh"] = True
    return customer


def test_moving_to_deciding_without_a_scope_form_is_refused(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "deciding"})
    assert r.status_code == 409
    assert r.get_json()["code"] == "needs_scope"


def test_scope_form_then_deciding_succeeds(client, logged_in):
    ok = client.post(f"/pipeline/api/customer/{logged_in.id}/scope",
                     json={"method": "verbal", "products": ["MAPD"]})
    assert ok.status_code == 200
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "deciding"})
    assert r.status_code == 200
    assert r.get_json()["customer"]["stage"] == "deciding"


def test_done_requires_an_outcome(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "done"})
    assert r.status_code == 400


def test_done_with_outcome_marks_settled(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/outcome",
                    json={"action": "done", "outcome": "kept"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["customer"]["settled"] is True
    assert body["customer"]["outcome"] == "kept"
    assert "counters" in body


def test_logging_a_touch_increments_attempts(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/touch",
                    json={"level": "tried", "channel": "call"})
    assert r.status_code == 200
    assert r.get_json()["customer"]["attempts"] == 1


def test_cannot_change_another_agents_customer(client, app, agency, admin_user, customer, db_session):
    """Agent of record is a compliance fact. Logging a touch is allowed;
    changing stage is not."""
    from app.models import Customer, PipelineState, PipelineConfig, User
    from app.extensions import db
    with app.app_context():
        c = db.session.get(Customer, customer.id)
        c.primary_agent_id = admin_user.id      # someone else's customer
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
    with app.app_context():
        other = User(email="other@test.com", name="Other", agency_id=agency.id)
        db.session.add(other)
        db.session.commit()
        oid = other.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(oid)
        sess["_fresh"] = True
    r = client.post(f"/pipeline/api/customer/{customer.id}/outcome",
                    json={"action": "done", "outcome": "kept"})
    assert r.status_code == 403

    # ...but logging what you did IS allowed on someone else's customer.
    ok = client.post(f"/pipeline/api/customer/{customer.id}/touch",
                     json={"level": "tried", "channel": "call"})
    assert ok.status_code == 200


def test_another_agency_cannot_mutate_at_all(client, app, agency, agent_user, customer, db_session):
    """Cross-tenant: a user of a DIFFERENT agency must never get a 200 back,
    on a write endpoint or on the permissive touch endpoint."""
    from app.models import Agency, Customer, PipelineState, PipelineConfig, User
    from app.extensions import db
    with app.app_context():
        c = db.session.get(Customer, customer.id)
        c.primary_agent_id = agent_user.id
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()

        other_agency = Agency(name="Other Agency")
        db.session.add(other_agency)
        db.session.commit()
        intruder = User(email="intruder@other.com", name="Intruder",
                        is_admin=True, agency_id=other_agency.id)
        db.session.add(intruder)
        db.session.commit()
        intruder_id = intruder.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(intruder_id)
        sess["_fresh"] = True

    for path, payload in (
        ("outcome", {"action": "done", "outcome": "kept"}),
        ("touch", {"level": "tried", "channel": "call"}),
        ("scope", {"method": "verbal", "products": ["MAPD"]}),
        ("waiting", {"what": "carrier", "due": "2026-11-01"}),
        ("tier", {"tier": 1}),
    ):
        r = client.post(f"/pipeline/api/customer/{customer.id}/{path}", json=payload)
        assert r.status_code in (403, 404), f"{path} leaked: {r.status_code}"

    # And nothing was written.
    with app.app_context():
        state = PipelineState.query.filter_by(customer_id=customer.id).one()
        assert state.stage == "contact"
        assert state.attempts == 0
        assert state.tier_override is None


def test_waiting_set_and_clear(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/waiting",
                    json={"what": "carrier letter", "due": "2026-11-05"})
    assert r.status_code == 200
    r = client.delete(f"/pipeline/api/customer/{logged_in.id}/waiting")
    assert r.status_code == 200


def test_tier_override_rejects_a_bad_value(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/tier", json={"tier": 9})
    assert r.status_code == 400
    ok = client.post(f"/pipeline/api/customer/{logged_in.id}/tier",
                     json={"tier": 1, "note": "state retiree"})
    assert ok.status_code == 200
    assert ok.get_json()["customer"]["tier"] == 1


def test_state_lookup_is_agency_scoped(app, agency, agent_user, customer, db_session, client):
    """The customer read is agency-scoped; the pipeline_state read must be too.
    A state row tagged to another agency must not be served just because the
    customer id matched."""
    from app.models import Agency, Customer, PipelineState, PipelineConfig
    from app.extensions import db
    with app.app_context():
        other_agency = Agency(name="Other")
        db.session.add(other_agency)
        db.session.commit()
        c = db.session.get(Customer, customer.id)
        c.primary_agent_id = agent_user.id
        db.session.add(PipelineState(agency_id=other_agency.id, customer_id=customer.id))
        db.session.add(PipelineConfig(agency_id=agency.id))
        db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(agent_user.id)
        sess["_fresh"] = True
    r = client.post(f"/pipeline/api/customer/{customer.id}/touch",
                    json={"level": "tried"})
    assert r.status_code == 404, f"leaked a foreign state row: {r.status_code}"


def test_malformed_waiting_due_is_a_400_not_a_500(client, logged_in):
    r = client.post(f"/pipeline/api/customer/{logged_in.id}/waiting",
                    json={"what": "carrier", "due": "not-a-date"})
    assert r.status_code == 400
