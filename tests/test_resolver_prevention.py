"""
tests/test_resolver_prevention.py

Tests for the corroborated composite matcher (name+DOB+zip-or-phone — name+DOB
alone is never enough for an auto match) and the strong-vs-weak prevention
boundary on the resolver's no-match tail: a strong identity (MBI,
carrier_member_id, or a composite match) creates a new customer + policy; a
weak identity enqueues a MatchSuggestion for human triage with NO phantom
policy. See .superpowers/sdd/task-2-brief.md.
"""
import json
import pytest
from datetime import date

from app.extensions import db
from app.models import Agency, User, Customer, Policy, MatchSuggestion
from app.commission.member_fact import MemberFact, RowClass
from app.commission.resolver import (
    _composite_match, has_strong_identity, resolve_customer, _enqueue_suggestion,
)


@pytest.fixture
def fixt(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        c = Customer(agency_id=ag.id, first_name="Jane", last_name="Doe",
                     full_name="Jane Doe", dob=date(1950, 1, 1), zip_code="28012",
                     phone_primary="7045551212")
        db.session.add(c)
        db.session.commit()
        yield ag.id, c.id


def test_composite_needs_corroborating_field(fixt, app):
    ag, cid = fixt
    with app.app_context():
        # name + dob ONLY → not enough → no auto match
        f1 = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950, 1, 1))
        assert _composite_match(f1, ag) == (None, None)
        # name + dob + zip → composite
        f2 = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950, 1, 1))
        f2.zip_code = "28012"
        c, conf = _composite_match(f2, ag)
        assert c is not None and conf == "composite"


def test_composite_matches_by_phone_too(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950, 1, 1))
        f.phone = "7045551212"
        c, conf = _composite_match(f, ag)
        assert c is not None and c.id == cid and conf == "composite"


def test_composite_no_match_when_zip_disagrees(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950, 1, 1))
        f.zip_code = "99999"
        assert _composite_match(f, ag) == (None, None)


def test_has_strong_identity(app):
    with app.app_context():
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x", mbi="1ABC")) is True
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x",
                                              carrier_member_id="999")) is True
        assert has_strong_identity(MemberFact(carrier="UHC", full_name="x")) is False


def test_has_strong_identity_via_composite_match(fixt, app):
    ag, cid = fixt
    with app.app_context():
        f = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                        last_name="Doe", dob=date(1950, 1, 1))
        f.zip_code = "28012"
        assert has_strong_identity(f, agency_id=ag) is True
        assert has_strong_identity(f) is False  # no agency_id → composite tier not consulted


# ---------------------------------------------------------------------------
# resolve_customer no-match tail: strong → create, weak → enqueue (no policy)
# ---------------------------------------------------------------------------

def test_composite_match_in_resolver_adopts_existing_customer(fixt, app, agent_user=None):
    ag, cid = fixt
    with app.app_context():
        from app.models import User
        u = User(name="A", email="a2@x.com", agency_id=ag); db.session.add(u); db.session.flush()
        fact = MemberFact(carrier="UHC", full_name="Jane Doe", first_name="Jane",
                          last_name="Doe", dob=date(1950, 1, 1),
                          row_class=RowClass.RENEWAL, amount=28.92,
                          effective_date=date(2026, 1, 1))
        fact.zip_code = "28012"
        r = resolve_customer(fact, agency_id=ag, agent_id=u.id, source="commission_import")
        assert r.customer.id == cid
        assert r.created_customer is False
        assert r.match_path == "composite"
        assert r.created_policy is True


def test_strong_identity_no_match_creates_new_customer(db_session, app):
    """MBI present, no existing match at all → §6 strong-identity create path."""
    from app.models import Agency, User
    with app.app_context():
        ag = Agency(name="T2"); db.session.add(ag); db.session.flush()
        u = User(name="B", email="b@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.commit()

        fact = MemberFact(carrier="UHC", full_name="Brand New", first_name="Brand",
                          last_name="New", mbi="NEWMBI001", row_class=RowClass.ENROLLMENT,
                          amount=200.0, effective_date=date(2026, 1, 1))
        r = resolve_customer(fact, agency_id=ag.id, agent_id=u.id, source="commission_import")

        assert r.created_customer is True
        assert r.created_policy is True
        assert r.match_path == "new_strong"
        assert r.customer.stub is True


def test_weak_identity_no_match_enqueues_no_phantom_policy(db_session, app):
    """No MBI, no carrier_member_id, no composite corroboration, no name+DOB
    near-match candidate → §6 weak-identity path: enqueue only, NO customer,
    NO policy created."""
    from app.models import Agency, User
    with app.app_context():
        ag = Agency(name="T3"); db.session.add(ag); db.session.flush()
        u = User(name="C", email="c@x.com", agency_id=ag.id); db.session.add(u); db.session.flush()
        db.session.commit()

        fact = MemberFact(carrier="Humana", full_name="Mystery Person",
                          first_name="Mystery", last_name="Person",
                          row_class=RowClass.RENEWAL, amount=29.94,
                          source_ref="humana::file::999")
        r = resolve_customer(fact, agency_id=ag.id, agent_id=u.id, source="commission_import")

        assert r.customer is None
        assert r.policy is None
        assert r.created_customer is False
        assert r.created_policy is False
        assert r.match_path == "needs_identity"
        assert "match_suggestion" in r.actions

        ms = MatchSuggestion.query.filter_by(agency_id=ag.id, status="pending").first()
        assert ms is not None
        assert ms.stub_customer_id is None
        assert ms.suggested_customer_id is None
        assert ms.confidence == "weak_identity"
        payload = json.loads(ms.source_member_fact_json)
        assert payload["full_name"] == "Mystery Person"


def test_enqueue_suggestion_is_null_tolerant_and_stores_fact_json(db_session, app):
    """_enqueue_suggestion must not crash when both stub_customer and candidate
    are None, and must persist a row with NULL stub/suggested ids + the fact
    JSON (incl. amount + writing agent when available)."""
    from app.models import Agency
    from app.commission.resolver import ResolveResult
    with app.app_context():
        ag = Agency(name="T4"); db.session.add(ag); db.session.flush()
        db.session.commit()

        fact = MemberFact(carrier="BCBS", full_name="No One", first_name="No",
                          last_name="One", amount=12.34, writing_agent_raw="Some Agent")
        result = ResolveResult()
        _enqueue_suggestion(fact, None, None, "weak_identity", ag.id, result)
        db.session.commit()

        ms = MatchSuggestion.query.filter_by(agency_id=ag.id).first()
        assert ms is not None
        assert ms.stub_customer_id is None
        assert ms.suggested_customer_id is None
        assert ms.confidence == "weak_identity"
        payload = json.loads(ms.source_member_fact_json)
        assert payload["full_name"] == "No One"
        assert payload.get("amount") == 12.34
        assert payload.get("writing_agent_raw") == "Some Agent"
