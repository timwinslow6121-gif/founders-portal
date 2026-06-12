"""
tests/test_commission_ledger.py

R1 commission ledger: per-carrier line-item extraction, split derivation,
balance/completeness self-check, idempotency. Fixtured from real raw commission
files in tests/fixtures/commission/. SQLite in-memory via conftest fixtures.
"""
import os
from datetime import date

import pytest

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


def test_registry_has_all_six_carriers_including_uhc():
    """UHC went live 2026-06-11 (validated raw parser). All six carriers are now
    registered in both the ledger EXTRACTORS and the NORMALIZERS pipeline."""
    from app.commission.ledger import EXTRACTORS
    from app.commission.normalizers import NORMALIZERS
    expected = {"Healthspring", "Devoted", "BCBS", "Aetna", "Humana", "UHC"}
    assert set(EXTRACTORS) == expected
    assert set(NORMALIZERS) == expected


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


def test_persist_line_items_backlinks_customer_id_by_mbi(db_session, agency):
    """Line items must carry customer_id (by MBI) so the recap can hyperlink the
    member name to their profile. The customer already exists (the ingest resolver
    created/matched it before persist_line_items runs)."""
    from app.models import CommissionLineItem, CommissionStatement, Customer
    from app.commission.ledger import LineItemDraft, persist_line_items, AGENT_COMMISSION
    from app.extensions import db
    from datetime import date

    cust = Customer(agency_id=agency.id, first_name="Jane", last_name="Doe",
                    full_name="Jane Doe", mbi="1AB2CD3EF45", source="bob")
    db.session.add(cust)
    stmt = CommissionStatement(agency_id=agency.id, carrier="UHC", agent_id=None,
                               period_label="May 2026", filename="u.xlsx",
                               statement_date=date(2026, 5, 1))
    db.session.add(stmt); db.session.flush()

    drafts = [
        LineItemDraft(carrier="UHC", source_ref="uhc::0::1", raw_amount=28.92,
                      split_rate=0.55, classification=AGENT_COMMISSION,
                      mbi="1AB2CD3EF45", member_name="DOE, JANE"),
        LineItemDraft(carrier="UHC", source_ref="uhc::0::2", raw_amount=4.59,
                      split_rate=None, classification="founders_override",
                      mbi="NOSUCHMBI99", member_name="GHOST, NO"),
    ]
    persist_line_items("UHC", drafts, stmt, agency.id)
    db.session.flush()

    rows = {li.source_ref: li for li in CommissionLineItem.query.filter_by(statement_id=stmt.id)}
    assert rows["uhc::0::1"].customer_id == cust.id    # matched by MBI
    assert rows["uhc::0::2"].customer_id is None        # no matching customer


@pytest.mark.parametrize("carrier,fixture", [
    ("Healthspring", "healthspring_sample.xlsx"),
    ("Devoted", "devoted_sample.xlsx"),
    ("BCBS", "bcbs_sample.xlsx"),
    ("Aetna", "aetna_sample.xlsx"),
    ("Humana", "humana_sample.xls"),
])
def test_every_carrier_balances_and_is_complete(carrier, fixture):
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    sheets = _load_fixture(fixture)
    extractor, _ = EXTRACTORS[carrier]
    drafts = extractor(sheets, split_lookup=lambda raw: 0.55)
    assert drafts, f"{carrier}: no line items extracted"
    report = verify_statement_balance(carrier, drafts, sheets)
    assert report.internal_ok, report
    assert report.completeness_ok, report


def test_devoted_format_detection():
    from app.commission.ledger import _devoted_format
    agency = _load_fixture("devoted_sample.xlsx")
    statement = _load_fixture("devoted_statement_sample.xlsx")
    assert _devoted_format(agency) == "agency"
    assert _devoted_format(statement) == "statement"


def test_devoted_format_unknown_raises():
    import pytest
    from app.commission.ledger import _devoted_format
    with pytest.raises(ValueError):
        _devoted_format({"Bogus": [["x"]]})


def test_devoted_filetoken():
    from app.commission.ledger import _devoted_filetoken
    agency = _load_fixture("devoted_sample.xlsx")
    statement = _load_fixture("devoted_statement_sample.xlsx")
    assert _devoted_filetoken(agency) == "agency"
    assert _devoted_filetoken(statement) == "npn20182775"


def test_devoted_agency_source_refs_are_file_tagged():
    from app.commission.ledger import extract_lineitems_devoted
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    assert drafts
    assert all(d.source_ref.startswith("devoted::agency::") for d in drafts)


def test_devoted_negative_override_is_chargeback_with_null_split():
    from app.commission.ledger import extract_lineitems_devoted, CHARGEBACK, FOUNDERS_OVERRIDE
    sheets = _load_fixture("devoted_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    override_rows = [d for d in drafts if "::Override::" in d.source_ref]
    assert override_rows
    for d in override_rows:
        if d.raw_amount < 0:
            assert d.classification == CHARGEBACK
            assert d.split_rate is None
        else:
            assert d.classification == FOUNDERS_OVERRIDE
            assert d.split_rate is None


def test_devoted_statement_extracts_detail_and_misc():
    from app.commission.ledger import (extract_lineitems_devoted, AGENT_COMMISSION,
                                        CHARGEBACK, HRA_BONUS)
    sheets = _load_fixture("devoted_statement_sample.xlsx")
    drafts = extract_lineitems_devoted(sheets, split_lookup=lambda raw: 0.55)
    detail = [d for d in drafts if "::Detail::" in d.source_ref]
    misc = [d for d in drafts if "::Misc::" in d.source_ref]
    assert len(detail) == 2
    assert len(misc) == 8
    assert all(d.classification == AGENT_COMMISSION for d in detail)
    assert all(d.classification == CHARGEBACK for d in misc)
    assert all(d.source_ref.startswith("devoted::npn20182775::") for d in drafts)
    assert not any("Summary" in d.source_ref for d in drafts)
    assert round(sum(d.raw_amount for d in drafts), 2) == -342.18


def test_devoted_statement_misc_positive_is_hra_bonus():
    from app.commission.ledger import _extract_devoted_statement, HRA_BONUS
    sheets = {
        "Summary": [["Description"]],
        "Detail": [["Statement Date", "Agent NPN"], ["05/29/2026", "20182775"]],
        "Misc": [["Rep Name", "Rep ID", "Amount", "Note"],
                 ["Rebekah Long", "20182775", "$50.00", "HRA for member X"]],
    }
    drafts = _extract_devoted_statement(sheets, "npn20182775", lambda raw: 0.55)
    misc = [d for d in drafts if "::Misc::" in d.source_ref]
    assert len(misc) == 1
    assert misc[0].classification == HRA_BONUS
    assert misc[0].split_rate == 0.55


def test_devoted_statement_money_rows_total():
    from app.commission.ledger import money_rows_total_devoted
    sheets = _load_fixture("devoted_statement_sample.xlsx")
    assert round(money_rows_total_devoted(sheets), 2) == -342.18


def test_devoted_two_files_coexist_and_file_scoped_replace(db_session, agency):
    """Persist agency line items, then statement line items, under ONE statement.
    Both coexist. Re-persisting the statement file replaces only its rows."""
    from app.models import CommissionLineItem, CommissionStatement
    from app.commission.ledger import (extract_lineitems_devoted, persist_line_items,
                                        _devoted_filetoken)
    from app.extensions import db
    from datetime import date

    stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted", agent_id=None,
                               period_label="April 2026", filename="d.xlsx",
                               statement_date=date(2026, 4, 1))
    db.session.add(stmt)
    db.session.flush()

    agency_sheets = _load_fixture("devoted_sample.xlsx")
    stmt_sheets = _load_fixture("devoted_statement_sample.xlsx")

    a_drafts = extract_lineitems_devoted(agency_sheets, split_lookup=lambda raw: 0.55)
    s_drafts = extract_lineitems_devoted(stmt_sheets, split_lookup=lambda raw: 0.55)

    persist_line_items("Devoted", a_drafts, stmt, agency.id)
    persist_line_items("Devoted", s_drafts, stmt, agency.id)
    db.session.flush()

    total = CommissionLineItem.query.filter_by(statement_id=stmt.id).count()
    assert total == len(a_drafts) + len(s_drafts)   # both files coexist

    token = _devoted_filetoken(stmt_sheets)          # "npn20182775"
    (CommissionLineItem.query
        .filter(CommissionLineItem.statement_id == stmt.id,
                CommissionLineItem.source_ref.like(f"devoted::{token}::%"))
        .delete(synchronize_session=False))
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == len(a_drafts)

    persist_line_items("Devoted", s_drafts, stmt, agency.id)
    db.session.flush()
    assert CommissionLineItem.query.filter_by(statement_id=stmt.id).count() == len(a_drafts) + len(s_drafts)


def test_devoted_both_files_each_balance_independently():
    from app.commission.ledger import EXTRACTORS, verify_statement_balance
    ext, _ = EXTRACTORS["Devoted"]
    for fixture, expected in [("devoted_sample.xlsx", None),
                              ("devoted_statement_sample.xlsx", -342.18)]:
        sheets = _load_fixture(fixture)
        drafts = ext(sheets, split_lookup=lambda raw: 0.55)
        report = verify_statement_balance("Devoted", drafts, sheets)
        assert report.internal_ok, report
        assert report.completeness_ok, report
        if expected is not None:
            assert round(report.lineitem_total, 2) == expected


def test_bcbs_per_agent_filetoken_and_file_scoped_prefix():
    """BCBS ships one file per agent. Each file's rows must carry a per-agent
    token (the P Number) so uploading agent B's file never wipes agent A's rows.
    Regression guard for the silent multi-agent data-loss bug."""
    from app.commission.ledger import (extract_lineitems_bcbs, _bcbs_filetoken,
                                        file_scoped_prefix, PER_AGENT_CARRIERS)
    # Two synthetic single-agent BCBS files with different P Numbers (col A).
    hdr = ["Agent #","Agent Name","Group Type","Customer Type","Customer Name",
           "Customer No","OrigEff","Product","CovFrom","CovTo","Period","OrigSub",
           "RenewalDate","Billed","Commission"]
    def f(pnum, name):
        return {"Sheet1": [hdr,
            [pnum, name, "RENEW", "MA", f"{name} Member", f"{pnum}-1",
             "2025-01-01","MAPD","","","",1,"", 52.0, 28.91]]}
    a = f("P0001", "ANJANA PATEL")
    j = f("P0002", "JUSTIN BASINGER")
    assert _bcbs_filetoken(a) == "pP0001"
    assert _bcbs_filetoken(j) == "pP0002"
    da = extract_lineitems_bcbs(a, split_lookup=lambda r: 0.55)
    dj = extract_lineitems_bcbs(j, split_lookup=lambda r: 0.55)
    assert all(x.source_ref.startswith("bcbs::pP0001::") for x in da)
    assert all(x.source_ref.startswith("bcbs::pP0002::") for x in dj)
    # tokens differ → file-scoped delete prefixes differ → no collision
    assert file_scoped_prefix("BCBS", a) == "bcbs::pP0001::%"
    assert file_scoped_prefix("BCBS", j) == "bcbs::pP0002::%"
    assert "BCBS" in PER_AGENT_CARRIERS and "Devoted" in PER_AGENT_CARRIERS
    # agency-wide carriers have no file-scoped prefix (blanket replace)
    assert file_scoped_prefix("Humana", {}) is None
    assert file_scoped_prefix("Aetna", {}) is None


def test_healthspring_multibatch_filetoken_from_filename():
    """Healthspring ships multiple batch files/month (NN_NNNNNN.xlsx) with no batch
    id in content — token comes from the filename via the ContextVar. Two batches
    must get distinct tokens so uploading batch 67 doesn't wipe batch 66."""
    from app.commission.ledger import (current_upload_filename, _healthspring_filetoken,
                                        file_scoped_prefix, PER_AGENT_CARRIERS,
                                        extract_lineitems_healthspring)
    sheets = _load_fixture("healthspring_sample.xlsx")

    current_upload_filename.set("66_481454.xlsx")
    assert _healthspring_filetoken(sheets) == "b66_481454"
    assert file_scoped_prefix("Healthspring", sheets) == "healthspring::b66_481454::%"
    d66 = extract_lineitems_healthspring(sheets, split_lookup=lambda r: 0.55)
    assert all(x.source_ref.startswith("healthspring::b66_481454::") for x in d66)

    current_upload_filename.set("68_486966.xlsx")
    assert _healthspring_filetoken(sheets) == "b68_486966"
    d68 = extract_lineitems_healthspring(sheets, split_lookup=lambda r: 0.55)
    assert all(x.source_ref.startswith("healthspring::b68_486966::") for x in d68)

    # unknown / non-batch filename → safe fallback
    current_upload_filename.set("")
    assert _healthspring_filetoken(sheets) == "batch"

    assert "Healthspring" in PER_AGENT_CARRIERS
