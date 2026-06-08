"""
tests/test_commission_ledger.py

R1 commission ledger: per-carrier line-item extraction, split derivation,
balance/completeness self-check, idempotency. Fixtured from real raw commission
files in tests/fixtures/commission/. SQLite in-memory via conftest fixtures.
"""
import os
from datetime import date

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def test_commission_lineitem_model_columns(db_session, agency):
    from app.models import CommissionLineItem, CommissionStatement
    from app.extensions import db

    stmt = CommissionStatement(
        agency_id=agency.id, carrier="BCBS", agent_id=None,
        period_label="April 2026", filename="x.xlsx",
        statement_date=date(2026, 4, 1),
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


def test_split_breakdown_agent_commission():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::1",
                       raw_amount=28.91, split_rate=0.55,
                       classification="agent_commission")
    payout, keep = split_breakdown(li)
    assert round(payout, 2) == 15.90      # 28.91 * 0.55
    assert round(keep, 2) == 13.01        # 28.91 - 15.90
    assert round(payout + keep, 2) == 28.91


def test_split_breakdown_founders_override_keeps_all():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="Healthspring", source_ref="healthspring::Detail::2",
                       raw_amount=100.0, split_rate=None,
                       classification="founders_override")
    payout, keep = split_breakdown(li)
    assert payout == 0.0
    assert keep == 100.0


def test_split_breakdown_chargeback_negative():
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="Devoted", source_ref="devoted::Agent Portion::5",
                       raw_amount=-347.0, split_rate=0.55,
                       classification="chargeback")
    payout, keep = split_breakdown(li)
    assert round(payout, 2) == -190.85    # -347 * 0.55
    assert round(keep, 2) == -156.15
    assert round(payout + keep, 2) == -347.0


def test_split_breakdown_none_split_rate_treated_as_zero_payout():
    # An agent_commission row whose agent had no contract (split_rate None):
    # payout is 0, keep is the whole raw amount (Founders keeps it pending fix).
    from app.commission.ledger import split_breakdown, LineItemDraft

    li = LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::9",
                       raw_amount=28.91, split_rate=None,
                       classification="agent_commission")
    payout, keep = split_breakdown(li)
    assert payout == 0.0
    assert keep == 28.91


def _load_fixture(name):
    from app.commission.sheet_loader import load_sheets
    return load_sheets(os.path.join(FIXTURES, name))


def test_healthspring_keeps_both_broker_and_service_fee():
    from app.commission.ledger import extract_lineitems_healthspring, FOUNDERS_OVERRIDE, AGENT_COMMISSION
    sheets = _load_fixture("healthspring_sample.xlsx")

    drafts = extract_lineitems_healthspring(sheets, split_lookup=lambda raw: 0.55)
    classes = [d.classification for d in drafts]

    # The override row that the normalizer DROPS must be present here.
    assert FOUNDERS_OVERRIDE in classes, "Service Fee (Founders override) row was dropped"
    assert AGENT_COMMISSION in classes, "Broker Level (agent commission) row missing"
    # Override rows carry no split.
    for d in drafts:
        if d.classification == FOUNDERS_OVERRIDE:
            assert d.split_rate is None
        if d.classification == AGENT_COMMISSION:
            assert d.split_rate == 0.55


def test_healthspring_money_rows_total_equals_lineitem_sum():
    from app.commission.ledger import (extract_lineitems_healthspring,
                                        money_rows_total_healthspring)
    sheets = _load_fixture("healthspring_sample.xlsx")
    drafts = extract_lineitems_healthspring(sheets, split_lookup=lambda raw: 0.55)
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_healthspring(sheets), 2)
