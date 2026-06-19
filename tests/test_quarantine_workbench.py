"""
tests/test_quarantine_workbench.py

The standalone Quarantine Workbench: all-months default grouped newest-first,
optional period/carrier/agent filters, and an amount sort that flattens the
month grouping so identical amounts cluster across months. Spec:
docs/superpowers/specs/2026-06-19-quarantine-workbench-design.md
"""
from datetime import date


def _mk_stmt(db, agency, *, carrier="UHC", period="June 2026", d=date(2026, 6, 1)):
    from app.models import CommissionStatement
    s = CommissionStatement(agency_id=agency.id, carrier=carrier, agent_id=None,
                            period_label=period, filename="x.xlsx", statement_date=d)
    db.session.add(s); db.session.flush()
    return s


def _mk_q(db, agency, stmt, *, raw, name, agent_id=None, ref):
    from app.models import CommissionLineItem
    li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier=stmt.carrier,
                            period_label=stmt.period_label, source_ref=ref, member_name=name,
                            raw_amount=raw, split_rate=None,
                            classification="needs_manual_review", payment_type="New",
                            agent_id=agent_id)
    db.session.add(li); db.session.flush()
    return li


def test_default_groups_by_month_newest_first(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantine_workbench
    with app.app_context():
        jun = _mk_stmt(db, agency, period="June 2026", d=date(2026, 6, 1))
        may = _mk_stmt(db, agency, period="May 2026", d=date(2026, 5, 1))
        _mk_q(db, agency, jun, raw=491.58, name="WINECOFF", ref="uhc::0::1")
        _mk_q(db, agency, jun, raw=125.0, name="CORUM", ref="uhc::0::2")
        _mk_q(db, agency, may, raw=491.58, name="MILES", ref="uhc::0::3")
        db.session.commit()

        wb = quarantine_workbench(agency.id)
        assert wb["grouped"] is True
        assert wb["count"] == 3
        assert round(wb["total"], 2) == round(491.58 + 125.0 + 491.58, 2)
        # newest month group first
        assert [g["period_label"] for g in wb["groups"]] == ["June 2026", "May 2026"]
        assert wb["groups"][0]["count"] == 2
        assert wb["groups"][1]["count"] == 1


def test_amount_sort_flattens_and_clusters_across_months(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantine_workbench
    with app.app_context():
        jun = _mk_stmt(db, agency, period="June 2026", d=date(2026, 6, 1))
        may = _mk_stmt(db, agency, period="May 2026", d=date(2026, 5, 1))
        _mk_q(db, agency, jun, raw=491.58, name="WINECOFF", ref="uhc::0::1")
        _mk_q(db, agency, jun, raw=125.0, name="CORUM", ref="uhc::0::2")
        _mk_q(db, agency, may, raw=491.58, name="MILES", ref="uhc::0::3")
        db.session.commit()

        wb = quarantine_workbench(agency.id, sort="amount_desc")
        assert wb["grouped"] is False
        amounts = [r["amount"] for r in wb["flat"]]
        assert amounts == [491.58, 491.58, 125.0]   # descending, identical clustered
        # the two 491.58 rows span different months (clustered across months)
        top_two_periods = {r["period_label"] for r in wb["flat"][:2]}
        assert top_two_periods == {"June 2026", "May 2026"}

        wb_asc = quarantine_workbench(agency.id, sort="amount_asc")
        assert [r["amount"] for r in wb_asc["flat"]] == [125.0, 491.58, 491.58]


def test_filters_narrow_by_period_carrier_agent(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantine_workbench
    with app.app_context():
        jun = _mk_stmt(db, agency, carrier="UHC", period="June 2026", d=date(2026, 6, 1))
        may = _mk_stmt(db, agency, carrier="UHC", period="May 2026", d=date(2026, 5, 1))
        bcbs = _mk_stmt(db, agency, carrier="BCBS", period="June 2026", d=date(2026, 6, 1))
        _mk_q(db, agency, jun, raw=125.0, name="A", agent_id=6, ref="uhc::0::1")
        _mk_q(db, agency, may, raw=200.0, name="B", agent_id=6, ref="uhc::0::2")
        _mk_q(db, agency, bcbs, raw=300.0, name="C", agent_id=7, ref="bcbs::0::1")
        db.session.commit()

        assert quarantine_workbench(agency.id, period="June 2026")["count"] == 2
        assert quarantine_workbench(agency.id, carrier="BCBS")["count"] == 1
        assert quarantine_workbench(agency.id, agent_id=6)["count"] == 2
        assert quarantine_workbench(agency.id, period="June 2026", carrier="UHC")["count"] == 1


def test_filter_options_only_list_periods_with_quarantine(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantine_workbench
    with app.app_context():
        jun = _mk_stmt(db, agency, period="June 2026", d=date(2026, 6, 1))
        _mk_q(db, agency, jun, raw=125.0, name="A", ref="uhc::0::1")
        db.session.commit()
        wb = quarantine_workbench(agency.id)
        assert "June 2026" in wb["filter_options"]["periods"]
        assert "UHC" in wb["filter_options"]["carriers"]


def test_empty_quarantine_is_clean(db_session, app, agency):
    from app.commission.recap import quarantine_workbench
    with app.app_context():
        wb = quarantine_workbench(agency.id)
        assert wb["count"] == 0
        assert wb["groups"] == []
        assert wb["total"] == 0.0


def test_total_count_helper(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantine_total_count
    with app.app_context():
        s = _mk_stmt(db, agency)
        _mk_q(db, agency, s, raw=125.0, name="A", ref="uhc::0::1")
        _mk_q(db, agency, s, raw=200.0, name="B", ref="uhc::0::2")
        db.session.commit()
        assert quarantine_total_count(agency.id) == 2


def test_workbench_page_renders_for_admin(db_session, app, client, agency):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(name="AJ", email="admin@test.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        s = _mk_stmt(db, agency, period="June 2026")
        _mk_q(db, agency, s, raw=491.58, name="WINECOFF", ref="uhc::0::1")
        db.session.commit()
        uid = admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get("/admin/commissions/quarantine")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Quarantine Workbench" in body
    assert "WINECOFF" in body
    assert "June 2026" in body
    # amount-sort variant flattens (renders without error)
    resp2 = client.get("/admin/commissions/quarantine?sort=amount_desc")
    assert resp2.status_code == 200


def test_workbench_page_forbidden_for_non_admin(db_session, app, client, agency):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        agent = User(name="Reg", email="reg@test.com", is_admin=False, agency_id=agency.id)
        db.session.add(agent); db.session.commit()
        uid = agent.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get("/admin/commissions/quarantine")
    assert resp.status_code == 403
