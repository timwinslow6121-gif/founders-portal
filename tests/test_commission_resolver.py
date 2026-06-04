"""
tests/test_commission_resolver.py

Tests for the commission→customer resolver: crosswalk, MBI reuse, stub-once,
carrier-switch interval, rapid_disenroll, suggest-link. SQLite in-memory via
conftest fixtures.
"""
import pytest
from datetime import date


def test_new_orm_columns_and_match_suggestion_model(db_session, app, agency):
    from app.models import Customer, Policy, MatchSuggestion
    from app.extensions import db

    with app.app_context():
        c = Customer(
            agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
            stub=True, source="commission_import",
        )
        db.session.add(c)
        db.session.flush()
        p = Policy(
            agency_id=agency.id, carrier="BCBS", member_id="106815011",
            rapid_disenroll=True, commission_split_flag="no_contract",
            customer_id=c.id,
        )
        db.session.add(p)
        db.session.flush()
        ms = MatchSuggestion(
            agency_id=agency.id, suggested_customer_id=c.id,
            confidence="name_dob", status="pending",
            source_member_fact_json="{}",
        )
        db.session.add(ms)
        db.session.commit()

        assert c.stub is True
        assert c.source == "commission_import"
        assert p.rapid_disenroll is True
        assert p.commission_split_flag == "no_contract"
        assert p.customer_id == c.id
        assert ms.status == "pending"
        assert ms.confidence == "name_dob"


def _seed_customer_with_policy(db, agency, agent, *, carrier, member_id, mbi=None,
                               first="Jane", last="Doe"):
    from app.models import Customer, Policy
    c = Customer(agency_id=agency.id, first_name=first, last_name=last,
                 full_name=f"{first} {last}", mbi=mbi, primary_agent_id=agent.id,
                 source="bob")
    db.session.add(c)
    db.session.flush()
    p = Policy(agency_id=agency.id, carrier=carrier, member_id=member_id, mbi=mbi,
              full_name=f"{first} {last}", status="active", agent_id=agent.id,
              customer_id=c.id)
    db.session.add(p)
    db.session.flush()
    return c, p


def test_crosswalk_reuses_existing_customer(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="BCBS", member_id="106815011",
            first="Brenda", last="Allen",
        )
        fact = MemberFact(
            carrier="BCBS", full_name="Allen,Brenda M", first_name="Brenda",
            last_name="Allen", carrier_member_id="106815011",
            row_class=RowClass.RENEWAL, amount=28.91,
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id          # reused, not new
        assert result.created_customer is False
        assert result.match_path == "crosswalk"
        assert result.customer.stub is False        # existing real customer untouched


def test_mbi_match_reuses_customer_and_creates_policy(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Bobby", last_name="Aderhold",
                     full_name="Bobby Aderhold", mbi="6CM1RV8NW05",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c)
        db.session.flush()

        fact = MemberFact(
            carrier="Aetna", full_name="ADERHOLD R,BOBBY", first_name="Bobby",
            last_name="Aderhold", mbi="6CM1RV8NW05", carrier_member_id="NG101350365000",
            plan_contract="H3146", plan_pbp="006", row_class=RowClass.RENEWAL, amount=28.92,
            effective_date=date(2026, 5, 1),
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id
        assert result.match_path == "mbi"
        assert result.created_customer is False
        assert result.created_policy is True
        assert result.policy.carrier == "Aetna"
        assert result.policy.member_id == "NG101350365000"
        assert result.policy.customer_id == c.id


def test_stub_created_once_then_crosswalk_relinks(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="BCBS", full_name="Newby,Sam", first_name="Sam", last_name="Newby",
            carrier_member_id="106999999", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 4, 1),
        )
        # First upload → stub created
        r1 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r1.created_customer is True
        assert r1.match_path == "stub"
        assert r1.customer.stub is True
        assert r1.customer.source == "commission_import"
        db.session.commit()

        # Second upload of the SAME fact → crosswalk re-link, NO new stub
        r2 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r2.created_customer is False
        assert r2.match_path == "crosswalk"
        assert r2.customer.id == r1.customer.id

        # Exactly one customer + one policy exist for this member
        assert Customer.query.filter_by(agency_id=agency.id).count() == 1
        assert Policy.query.filter_by(agency_id=agency.id, member_id="106999999").count() == 1


def test_rapid_disenroll_flag_set_when_under_90_days(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="Devoted", full_name="Elizabeth Bolder", first_name="Elizabeth",
            last_name="Bolder", carrier_member_id="DS97W3", mbi="1X57MJ7FA64",
            row_class=RowClass.CHARGEBACK, amount=-347.0,
            effective_date=date(2026, 1, 1), term_date=date(2026, 3, 31),  # < 90d
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")
        assert r.policy.rapid_disenroll is True
        assert "rapid_disenroll" in r.actions


def test_carrier_switch_terms_old_policy_and_opens_new_interval(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Dorothy", last_name="Smith",
                     full_name="Dorothy Smith", mbi="9ZZ9ZZ9ZZ99",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c); db.session.flush()
        old = Policy(agency_id=agency.id, carrier="Humana", member_id="PID123",
                     mbi="9ZZ9ZZ9ZZ99", status="active", agent_id=agent_user.id,
                     customer_id=c.id, effective_date=date(2025, 1, 1))
        db.session.add(old); db.session.flush()

        fact = MemberFact(
            carrier="BCBS", full_name="Smith,Dorothy", first_name="Dorothy",
            last_name="Smith", carrier_member_id="106800000", mbi="9ZZ9ZZ9ZZ99",
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        assert r.customer.id == c.id
        db.session.refresh(old)
        assert old.status == "termed"
        assert "carrier_switch" in r.actions
        intervals = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").all()
        assert len(intervals) == 1
        assert intervals[0].end_date is None
