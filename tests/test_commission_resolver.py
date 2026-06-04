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
