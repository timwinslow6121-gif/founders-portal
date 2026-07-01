"""
tests/test_customer_merge.py

TDD tests for merge_customers() in app/customers.py.

PolicyPayment has NO customer_id column — it links to a customer only through
policy_id → Policy.customer_id. When a loser's Policy moves to the keeper, that
policy's payments follow automatically (transitive reattachment).
"""
import pytest
from datetime import date

from app.extensions import db
from app.models import (
    Agency, User, Customer, Policy, PolicyPayment, CommissionStatement,
    CustomerNote, CustomerContact, CustomerAorHistory,
)
from app.customers import merge_customers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _agency_user(db_session):
    """Return (agency_id, actor_user) — already flushed."""
    ag = Agency(name="T")
    db.session.add(ag)
    db.session.flush()
    u = User(email="actor@test.com", name="Actor", agency_id=ag.id, is_admin=True)
    db.session.add(u)
    db.session.flush()
    return ag.id, u


def _c(agency_id, **kw):
    """Create and flush a Customer with required defaults."""
    base = dict(agency_id=agency_id, first_name="", last_name="", stub=False)
    base.update(kw)
    c = Customer(**base)
    db.session.add(c)
    db.session.flush()
    return c


def _stmt(agency_id):
    """Create and flush a minimal CommissionStatement (required by PolicyPayment)."""
    s = CommissionStatement(
        agency_id=agency_id,
        carrier="UHC",
        statement_date=date(2026, 5, 1),
        period_label="May 2026",
    )
    db.session.add(s)
    db.session.flush()
    return s


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_merge_reattaches_all_children_and_fills_blanks(db_session, app):
    """
    merge_customers moves all child records to keeper and fills keeper's blank
    fields from the loser.  PolicyPayment follows transitively via Policy.
    """
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="John", last_name="Connelly",
                    full_name="John Connelly", mbi="4RH5X85DC65",
                    dob=date(1953, 4, 7))
        loser  = _c(agency_id, full_name="CONNELLY, JOHN", stub=True,
                    phone_primary="828-555-0100")  # keeper has no phone

        # Policy on the loser — its payments follow transitively
        loser_policy = Policy(agency_id=agency_id, carrier="UHC",
                              member_id="M1", customer_id=loser.id)
        db.session.add(loser_policy)
        db.session.flush()  # need policy.id for PaymentStatement link

        stmt = _stmt(agency_id)
        payment = PolicyPayment(
            agency_id=agency_id,
            statement_id=stmt.id,
            carrier="UHC",
            period_label="May 2026",
            member_name="John Connelly",
            commission_action="renewal",
            paid_amount=28.92,
            policy_id=loser_policy.id,
            source_ref="uhc::x::S::0",
        )
        db.session.add(payment)

        db.session.add(CustomerNote(
            customer_id=loser.id, agent_id=actor.id,
            note_text="hi",
        ))
        db.session.add(CustomerContact(
            customer_id=loser.id, contact_name="x",
        ))
        db.session.add(CustomerAorHistory(
            customer_id=loser.id, agent_id=actor.id,
            carrier="UHC", effective_date=date(2025, 1, 1),
        ))
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert res["merged"] == 1

        # loser deleted
        assert db.session.get(Customer, loser.id) is None

        # child records moved to keeper
        assert Policy.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerNote.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerContact.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerAorHistory.query.filter_by(customer_id=keeper.id).count() == 1

        # PolicyPayment follows transitively (via policy, not a direct customer_id column)
        db.session.refresh(payment)
        assert payment.policy.customer_id == keeper.id

        # PolicyPayment count reported in moved dict
        assert res["moved"]["PolicyPayment"] >= 1

        # blank field filled from loser
        db.session.refresh(keeper)
        assert keeper.phone_primary == "828-555-0100"
        assert "phone_primary" in res["filled"]


def test_merge_never_overwrites_keeper_value(db_session, app):
    """Keeper's existing field values must never be overwritten."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                    phone_primary="111-111-1111")
        loser  = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                    stub=True, phone_primary="222-222-2222")
        db.session.commit()

        merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        db.session.refresh(keeper)
        assert keeper.phone_primary == "111-111-1111"   # kept, not overwritten


def test_merge_refuses_contradictory_dob(db_session, app):
    """Return ok=False when keeper + loser have different non-null DOBs."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="C", last_name="D", full_name="C D",
                    dob=date(1950, 1, 1))
        loser  = _c(agency_id, first_name="C", last_name="D", full_name="C D",
                    dob=date(1961, 2, 2))
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)

        assert res["ok"] is False
        assert "contradict" in res["error"].lower()
        # nothing deleted
        assert db.session.get(Customer, loser.id) is not None


def test_merge_is_idempotent_on_missing_loser(db_session, app):
    """When no loser IDs resolve (already merged / nonexistent), return ok=True merged=0."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="E", last_name="F", full_name="E F")
        db.session.commit()

        res = merge_customers(keeper.id, [99999], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert res["merged"] == 0
