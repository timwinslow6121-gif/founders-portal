"""
tests/test_balance_gate.py

A3 — the balance GATE. The completeness check (verify_statement_balance) already
runs on every upload; A3 PERSISTS its result on the statement so it can be shown
as a visible status (✓ balances / ✗ off by $X) instead of only logging a warning.
"""
from datetime import date


def test_statement_has_balance_columns(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionStatement
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                statement_date=date(2026, 5, 1), period_label="May 2026",
                                balanced=True, ledger_total=70466.86,
                                money_rows_total=70466.86)
        db.session.add(s); db.session.commit()
        got = CommissionStatement.query.first()
        assert got.balanced is True
        assert got.ledger_total == 70466.86
        assert got.money_rows_total == 70466.86


def test_balance_status_helper():
    """balance_status(stmt) -> ('ok'|'off'|'unknown', delta) drives the badge."""
    from app.commission.recap import balance_status

    class S:
        def __init__(self, balanced, lt, mt):
            self.balanced, self.ledger_total, self.money_rows_total = balanced, lt, mt

    assert balance_status(S(True, 100.0, 100.0)) == ("ok", 0.0)
    state, delta = balance_status(S(False, 100.0, 99.73))
    assert state == "off" and abs(delta - 0.27) < 0.001
    assert balance_status(S(None, None, None)) == ("unknown", 0.0)


def test_fidelity_view_shows_every_row_with_split_that_ties(db_session, app, agency):
    """A2 — the Fidelity View lists every line item with raw/agent/founders, and the
    agent + founders columns sum back to raw (G+H=F), proving nothing is lost."""
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem
    from app.commission.recap import fidelity_view
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(s); db.session.flush()
        # an agent_commission row (splits) + a founders_override row (100% Founders)
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id,
            carrier="UHC", source_ref="a", member_name="DOE, JANE", raw_amount=28.92,
            split_rate=0.55, classification="agent_commission"))
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id,
            carrier="UHC", source_ref="b", member_name="DOE, JANE", raw_amount=4.59,
            split_rate=None, classification="founders_override"))
        db.session.commit()
        fv = fidelity_view(s.id, agency.id)
        assert fv["count"] == 2
        assert fv["raw_total"] == round(28.92 + 4.59, 2)
        # agent + founders columns reconcile to the raw total (G+H=F)
        assert round(fv["agent_total"] + fv["founders_total"], 2) == fv["raw_total"]
        assert fv["balances"] is True
        # the override row gives the agent nothing, Founders the whole amount
        ovr = next(r for r in fv["rows"] if r["classification"] == "founders_override")
        assert ovr["agent"] == 0.0 and ovr["founders"] == 4.59


def test_fidelity_page_renders_for_admin(db_session, app, client, agency):
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    with app.app_context():
        admin = User(name="AJ", email="fa@x.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
            statement_date=date(2026, 5, 1), period_label="May 2026",
            balanced=True, ledger_total=33.51, money_rows_total=33.51)
        db.session.add(s); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id,
            carrier="UHC", source_ref="a", member_name="DOE, JANE", raw_amount=28.92,
            split_rate=0.55, classification="agent_commission"))
        db.session.commit()
        sid, aid = s.id, admin.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    r = client.get(f"/admin/commissions/{sid}/fidelity")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Fidelity" in body and "Jane Doe" in body   # name normalized for display
    assert "Balances to the penny" in body


def test_fidelity_page_403_for_non_admin(db_session, app, client, agency):
    from app.extensions import db
    from app.models import User, CommissionStatement
    with app.app_context():
        agent = User(name="Reg", email="fr@x.com", is_admin=False, agency_id=agency.id)
        db.session.add(agent)
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
            statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(s); db.session.commit()
        sid, gid = s.id, agent.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(gid)
    assert client.get(f"/admin/commissions/{sid}/fidelity").status_code == 403


def test_commission_audit_overview_checklist_and_statements(db_session, app, agency, agent_user):
    """The redesigned audit overview: statements for the period w/ balance + quarantine,
    plus a carrier checklist (from active contracts) marking uploaded vs missing."""
    from app.extensions import db
    from app.models import (CommissionStatement, CommissionLineItem, AgentCarrierContract)
    from app.commission.recap import commission_audit_overview
    with app.app_context():
        # agent contracted with UHC, Humana, GTL (3 expected carriers)
        for c in ("UHC", "Humana", "GTL"):
            db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=agent_user.id,
                                                carrier=c, is_active=True, split_rate=0.55))
        # only UHC uploaded for the period (balanced) with 2 quarantined
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
            statement_date=date(2026, 5, 1), period_label="May 2026",
            balanced=True, ledger_total=100.0, money_rows_total=100.0)
        db.session.add(s); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id, carrier="UHC",
            source_ref="q1", raw_amount=50.0, split_rate=None,
            classification="needs_manual_review"))
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id, carrier="UHC",
            source_ref="q2", raw_amount=50.0, split_rate=None,
            classification="needs_manual_review"))
        db.session.commit()

        ov = commission_audit_overview(agency.id, "May 2026")
        assert ov["statement_count"] == 1
        assert ov["total_quarantined"] == 2
        assert ov["statements"][0]["balance_state"] == "ok"
        assert ov["statements"][0]["quarantined"] == 2
        # checklist: UHC uploaded ✓, Humana + GTL still missing
        cl = {c["carrier"]: c["uploaded"] for c in ov["checklist"]}
        assert cl == {"UHC": True, "Humana": False, "GTL": False}
        assert ov["carriers_uploaded"] == 1 and ov["carriers_expected"] == 3


def test_admin_commission_page_shows_trust_strip_and_fidelity_link(db_session, app, client, agency, agent_user):
    """The redesigned admin Commission Audit page renders the trust strip + carrier
    checklist + a per-statement Fidelity link (the bug: Fidelity was unreachable as
    admin)."""
    from app.extensions import db
    from app.models import User, CommissionStatement, AgentCarrierContract
    with app.app_context():
        admin = User(name="AJ", email="adm@x.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=agent_user.id,
                                            carrier="UHC", is_active=True, split_rate=0.55))
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
            statement_date=date(2026, 5, 1), period_label="May 2026",
            balanced=True, ledger_total=100.0, money_rows_total=100.0)
        db.session.add(s); db.session.commit()
        aid, sid = admin.id, s.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    r = client.get("/admin/commissions?period=May%202026")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Statements uploaded" in body          # trust strip
    assert "✓ UHC" in body or "UHC" in body        # carrier checklist
    assert f"/admin/commissions/{sid}/fidelity" in body   # Fidelity reachable as admin
    assert "✓ Balances" in body                    # per-statement balance badge


def test_friendly_payment_type_translates_carrier_codes():
    from app.commission.recap import friendly_payment_type
    assert friendly_payment_type("arcm")[0] == "Renewal commission (monthly)"
    assert friendly_payment_type("fy")[0] == "First-year commission"
    assert friendly_payment_type("initial - new to cms")[0] == "Initial — new to Medicare"
    # raw code preserved for the hover
    assert friendly_payment_type("arcm")[1] == "arcm"
    # unknown passes through (nothing hidden)
    assert friendly_payment_type("WeirdCode")[1] == "WeirdCode"
    assert friendly_payment_type("")[0] == "—"


def test_fidelity_page_has_inline_edit_form(db_session, app, client, agency, agent_user):
    """AJ can correct a split right on the Fidelity View — the per-row Edit form
    posts to the existing commission_line_edit route."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    with app.app_context():
        admin = User(name="AJ", email="fe@x.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        s = CommissionStatement(agency_id=agency.id, carrier="Humana",
            statement_date=date(2026, 5, 1), period_label="May 2026",
            balanced=True, ledger_total=28.92, money_rows_total=28.92)
        db.session.add(s); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=s.id, carrier="Humana",
            source_ref="a", member_name="ROE, BOB", raw_amount=28.92, split_rate=0.55,
            classification="agent_commission", payment_type="arcm", agent_id=agent_user.id)
        db.session.add(li); db.session.commit()
        sid, lid, aid = s.id, li.id, admin.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    body = client.get(f"/admin/commissions/{sid}/fidelity").get_data(as_text=True)
    assert "Renewal commission (monthly)" in body         # friendly label for arcm
    # quirk #3: lazy edit form — the edit endpoint is wired via a JS constant (one
    # form built on Edit-click), NOT ~4k hidden per-row forms. The Edit button + the
    # once-rendered agents template + the row data attributes must all be present.
    assert "/admin/commissions/line/0/edit" in body        # FD_EDIT_URL (JS swaps the id)
    assert "fd-edit-btn" in body                            # per-row Edit button
    assert 'id="fd-agents-tpl"' in body                    # agents list rendered ONCE
    assert "fdedit-" not in body                            # NO per-row hidden forms (the bloat)
    assert 'data-agent-amt' in body and 'data-founders-amt' in body  # row data for the lazy form
    # #6/#7: sticky-scroll container + sortable headers + agent filter
    assert "fd-scroll" in body
    assert 'data-sort="member"' in body and 'data-sort="amount"' in body
    assert 'id="fdAgent"' in body


def test_display_name_normalizes_carrier_names():
    from app.commission.recap import display_name
    assert display_name("WINECOFF, JACK J.") == "Jack J. Winecoff"
    assert display_name("SMITH, JOHN") == "John Smith"
    assert display_name("BROWN JR, TOCARA A") == "Tocara A. Brown Jr"
    assert display_name("") == ""


def test_fidelity_view_enriched_fields(db_session, app, agency, agent_user):
    """Fidelity rows now carry agent name, split rate, a calc label + full rule, a
    proper-case display name, customer link, and a chargeback flag."""
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem, Customer
    from app.commission.recap import fidelity_view
    with app.app_context():
        cust = Customer(agency_id=agency.id, first_name="Jane", last_name="Doe",
                        full_name="Jane Doe", mbi="MBIX1")
        db.session.add(cust); db.session.flush()
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(s); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id, carrier="UHC",
            source_ref="a", member_name="DOE, JANE", customer_id=cust.id, raw_amount=28.92,
            split_rate=0.55, classification="agent_commission", payment_type="renewal",
            agent_id=agent_user.id))
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id, carrier="UHC",
            source_ref="b", member_name="DOE, JANE", raw_amount=-28.92, split_rate=0.55,
            classification="chargeback", payment_type="renewal chargeback"))
        db.session.commit()
        fv = fidelity_view(s.id, agency.id)
        comm = next(r for r in fv["rows"] if r["classification"] == "agent_commission")
        assert comm["member_display"] == "Jane Doe"
        assert comm["customer_id"] == cust.id
        assert comm["agent_name"] == agent_user.display_name
        assert comm["split_rate"] == 0.55
        assert "55%" in comm["calc_label"]
        assert "agent" in comm["calc_rule"].lower()
        assert comm["is_chargeback"] is False
        cb = next(r for r in fv["rows"] if r["classification"] == "chargeback")
        assert cb["is_chargeback"] is True


def test_recompute_ledger_total_from_line_items(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem
    from app.commission.recap import recompute_ledger_total
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(s); db.session.flush()
        for amt, ref in [(28.92, "a"), (4.59, "b"), (-10.0, "c")]:
            db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=s.id,
                carrier="UHC", source_ref=ref, raw_amount=amt, split_rate=None,
                classification="agent_commission"))
        db.session.commit()
        total = recompute_ledger_total(s, agency.id)
        assert total == round(28.92 + 4.59 - 10.0, 2)
        assert s.ledger_total == total


def test_upload_persists_balance_result(db_session, app, agency):
    """The balance report from verify_statement_balance must be STORED on the
    statement (the A3 change), so the status is shown not just logged. Simulates the
    upload's store step: balanced + both totals land on the statement."""
    from app.extensions import db
    from app.models import CommissionStatement
    from app.commission.ledger import BalanceReport
    from app.commission.recap import balance_status
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(s); db.session.flush()
        # mirror the route's store step
        report = BalanceReport(carrier="UHC", lineitem_total=70466.86,
                               money_rows_total=70466.86, agent_payout_total=0.0,
                               founders_keep_total=0.0, internal_ok=True,
                               completeness_ok=True)
        s.balanced = bool(report.completeness_ok and report.internal_ok)
        s.ledger_total = report.lineitem_total
        s.money_rows_total = report.money_rows_total
        db.session.commit()
        assert balance_status(s) == ("ok", 0.0)

        # an off-balance statement surfaces the delta
        report2 = BalanceReport(carrier="BCBS", lineitem_total=5475.68,
                                money_rows_total=5475.95, agent_payout_total=0.0,
                                founders_keep_total=0.0, internal_ok=True,
                                completeness_ok=False)
        s.balanced = bool(report2.completeness_ok and report2.internal_ok)
        s.ledger_total = report2.lineitem_total
        s.money_rows_total = report2.money_rows_total
        state, delta = balance_status(s)
        assert state == "off" and abs(delta + 0.27) < 0.001
