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
