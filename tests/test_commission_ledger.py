"""
tests/test_commission_ledger.py

R1 commission ledger: per-carrier line-item extraction, split derivation,
balance/completeness self-check, idempotency. Fixtured from real raw commission
files in tests/fixtures/commission/. SQLite in-memory via conftest fixtures.
"""
import os

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def test_commission_lineitem_model_columns(db_session, agency):
    from app.models import CommissionLineItem, CommissionStatement
    from app.extensions import db

    stmt = CommissionStatement(
        agency_id=agency.id, carrier="BCBS", agent_id=None,
        period_label="April 2026", filename="x.xlsx",
    )
    db.session.add(stmt)
    db.session.flush()

    li = CommissionLineItem(
        agency_id=agency.id,
        statement_id=stmt.id,
        carrier="BCBS",
        period_label="April 2026",
        source_ref="bcbs::Sheet1::1",
        member_name="DOE,JANE",
        raw_amount=28.91,
        split_rate=0.55,
        classification="agent_commission",
        payment_type="renewal",
    )
    db.session.add(li)
    db.session.flush()

    got = CommissionLineItem.query.filter_by(statement_id=stmt.id).first()
    assert got.raw_amount == 28.91
    assert got.split_rate == 0.55
    assert got.classification == "agent_commission"
    assert got.agent_id is None        # nullable
    assert got.customer_id is None     # nullable
    assert got.mbi is None             # nullable
