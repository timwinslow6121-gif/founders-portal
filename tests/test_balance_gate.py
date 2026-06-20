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
    assert "Fidelity" in body and "DOE, JANE" in body
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
