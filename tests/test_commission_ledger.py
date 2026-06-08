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


def test_bcbs_uses_commission_column_and_records_zero_rows():
    from app.commission.ledger import extract_lineitems_bcbs, money_rows_total_bcbs, AGENT_COMMISSION, CHARGEBACK
    sheets = _load_fixture("bcbs_sample.xlsx")
    drafts = extract_lineitems_bcbs(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no BCBS line items extracted"
    for d in drafts:
        assert d.classification in (AGENT_COMMISSION, CHARGEBACK)
        assert d.split_rate == 0.55
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_bcbs(sheets), 2)


def test_aetna_extracts_payee_amount_rows():
    from app.commission.ledger import extract_lineitems_aetna, money_rows_total_aetna
    sheets = _load_fixture("aetna_sample.xlsx")
    drafts = extract_lineitems_aetna(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no Aetna line items extracted"
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_aetna(sheets), 2)


def test_devoted_produces_override_agent_and_hra():
    from app.commission.ledger import (extract_lineitems_devoted, money_rows_total_devoted,
                                        FOUNDERS_OVERRIDE, AGENT_COMMISSION, HRA_BONUS)
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    classes = {d.classification for d in drafts}
    # Override must be present (the row the normalizer collapses away).
    assert FOUNDERS_OVERRIDE in classes
    assert AGENT_COMMISSION in classes
    # HRA may or may not be in this fixture; if present it is hra_bonus with split.
    for d in drafts:
        if d.classification == HRA_BONUS:
            assert d.split_rate == 0.55
        if d.classification == FOUNDERS_OVERRIDE:
            assert d.split_rate is None
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_devoted(sheets), 2)


def test_humana_classifies_and_totals():
    from app.commission.ledger import extract_lineitems_humana, money_rows_total_humana
    sheets = _load_fixture("humana_sample.xls")
    drafts = extract_lineitems_humana(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, "no Humana line items extracted"
    assert round(sum(d.raw_amount for d in drafts), 2) == round(money_rows_total_humana(sheets), 2)


def test_registry_has_five_clean_carriers_not_uhc():
    from app.commission.ledger import EXTRACTORS
    assert set(EXTRACTORS) == {"Healthspring", "Devoted", "BCBS", "Aetna", "Humana"}
    assert "UHC" not in EXTRACTORS


def test_verify_statement_balance_internal_and_completeness():
    # Build line items in-memory from a fixture, then verify against the sheets.
    from app.commission.ledger import EXTRACTORS, verify_statement_balance, split_breakdown
    sheets = _load_fixture("bcbs_sample.xlsx")
    extractor, _money = EXTRACTORS["BCBS"]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)

    report = verify_statement_balance("BCBS", drafts, sheets)
    assert report.internal_ok, report
    assert report.completeness_ok, report
    # Internal balance: every draft's payout + keep == its raw.
    for d in drafts:
        p, k = split_breakdown(d)
        assert round(p + k, 2) == round(d.raw_amount, 2)


def test_verify_statement_balance_fails_when_a_row_dropped():
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    sheets = _load_fixture("bcbs_sample.xlsx")
    extractor, _money = EXTRACTORS["BCBS"]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)
    assert len(drafts) >= 2
    dropped = drafts[:-1]                 # simulate the extractor losing a row
    report = verify_statement_balance("BCBS", dropped, sheets)
    assert report.completeness_ok is False


def test_persist_line_items_resolves_agent_and_is_idempotent(db_session, agency):
    from app.models import CommissionLineItem, CommissionStatement, User
    from app.commission.ledger import LineItemDraft, persist_line_items, AGENT_COMMISSION
    from app.extensions import db
    from datetime import date

    agent = User(name="Justin Basinger", email="justin@x.com", agency_id=agency.id)
    db.session.add(agent)
    stmt = CommissionStatement(agency_id=agency.id, carrier="BCBS", agent_id=None,
                               period_label="April 2026", filename="b.xlsx",
                               statement_date=date(2026, 4, 1))
    db.session.add(stmt)
    db.session.flush()

    drafts = [LineItemDraft(carrier="BCBS", source_ref="bcbs::Sheet1::1",
                            raw_amount=28.91, split_rate=0.55,
                            classification=AGENT_COMMISSION,
                            writing_agent_raw="Basinger, Justin")]

    def resolver(raw):
        return agent.id if "basinger" in raw.lower() else None

    n1 = persist_line_items("BCBS", drafts, stmt, agency.id, agent_resolver=resolver)
    db.session.flush()
    rows = CommissionLineItem.query.filter_by(statement_id=stmt.id).all()
    assert n1 == 1 and len(rows) == 1
    assert rows[0].agent_id == agent.id

    # Re-run: same source_ref updates in place, no duplicate.
    persist_line_items("BCBS", drafts, stmt, agency.id, agent_resolver=resolver)
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == 1
