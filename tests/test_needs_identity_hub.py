"""
tests/test_needs_identity_hub.py

Task 7: broaden /customers/unassigned into the 4-category Needs Identity hub
(agent | match | name | interval). Reuses the existing "needs agent" behavior
as cat=agent; adds three new category builders selected by ?cat=.
"""
import pytest
from datetime import date
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, CommissionLineItem,
                         CommissionStatement, CustomerAorHistory)


def test_hub_categories_render(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ", email="admin@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        db.session.add(Customer(agency_id=ag.id, first_name="No", last_name="Agent", full_name="No Agent", primary_agent_id=None))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        # default page lists categories + counts; needs-agent shows the unassigned customer
        resp = client.get("/customers/unassigned?cat=agent")
        assert resp.status_code == 200
        assert b"No Agent" in resp.data


def test_hub_default_cat_is_agent(db_session, app):
    with app.app_context():
        ag = Agency(name="T2"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ2", email="admin2@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        db.session.add(Customer(agency_id=ag.id, first_name="Default", last_name="CatCust", full_name="Default Cat Cust", primary_agent_id=None))
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        resp = client.get("/customers/unassigned")
        assert resp.status_code == 200
        assert b"Default Cat Cust" in resp.data


def test_hub_match_category_lists_unmatched_line_item(db_session, app):
    with app.app_context():
        ag = Agency(name="T3"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ3", email="admin3@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        db.session.flush()
        stmt = CommissionStatement(agency_id=ag.id, carrier="UHC", period_label="2026-06",
                                    statement_date=date(2026, 6, 1))
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=ag.id, statement_id=stmt.id, carrier="UHC",
                                 period_label="2026-06", source_ref="uhc::1",
                                 customer_id=None, member_name="Smith, Jane",
                                 raw_amount=42.50, classification="agent_commission")
        db.session.add(li)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        resp = client.get("/customers/unassigned?cat=match")
        assert resp.status_code == 200
        assert b"Smith, Jane" in resp.data


def test_hub_name_category_lists_blank_name_active_policy(db_session, app):
    with app.app_context():
        ag = Agency(name="T4"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ4", email="admin4@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        db.session.flush()
        pol = Policy(agency_id=ag.id, carrier="Humana", member_id="H999",
                     first_name=None, last_name=None, status="active")
        db.session.add(pol)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        resp = client.get("/customers/unassigned?cat=name")
        assert resp.status_code == 200
        assert b"H999" in resp.data


def test_hub_interval_category_lists_agented_customer_with_no_interval(db_session, app):
    with app.app_context():
        ag = Agency(name="T5"); db.session.add(ag); db.session.flush()
        admin = User(name="AJ5", email="admin5@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=True); db.session.add(admin)
        agent = User(name="Bob Agent", email="bob5@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=False)
        db.session.add(agent); db.session.flush()
        cust = Customer(agency_id=ag.id, first_name="Has", last_name="Interval", full_name="Has Agent No Interval",
                         primary_agent_id=agent.id)
        db.session.add(cust)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(admin.id)
        resp = client.get("/customers/unassigned?cat=interval")
        assert resp.status_code == 200
        assert b"Has Agent No Interval" in resp.data


def test_hub_non_admin_forbidden(db_session, app):
    with app.app_context():
        ag = Agency(name="T6"); db.session.add(ag); db.session.flush()
        agent = User(name="Plain Agent", email="plain6@foundersinsuranceagency.com",
                     agency_id=ag.id, is_admin=False)
        db.session.add(agent)
        db.session.commit()
        client = app.test_client()
        with client.session_transaction() as s:
            s["_user_id"] = str(agent.id)
        resp = client.get("/customers/unassigned")
        assert resp.status_code == 403
