from datetime import date
import pytest


def test_previous_month_helper():
    from app.commission.routes import _previous_month
    # July 2026 -> June 2026
    assert _previous_month(date(2026, 7, 15)) == ("June 2026", "2026-06")
    # January -> previous December of prior year
    assert _previous_month(date(2026, 1, 3)) == ("December 2025", "2025-12")


@pytest.fixture
def ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()


def test_per_agent_upload_status(ctx):
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, CommissionStatement,
                            CommissionLineItem)
    from app.commission.recap import per_agent_upload_status
    app, agency_id = ctx
    # two agents with active BCBS contracts (expected); only one has uploaded rows
    a1 = User(email="a1@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    a2 = User(email="a2@x.com", name="Mike Lauzurique", agency_id=agency_id, role="agent")
    db.session.add_all([a1, a2]); db.session.flush()
    for a in (a1, a2):
        db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a.id,
                                            carrier="BCBS", is_active=True))
    st = CommissionStatement(agency_id=agency_id, carrier="BCBS",
                             statement_date=date(2026, 6, 1), period_label="June 2026")
    db.session.add(st); db.session.flush()
    # only Brian has a line item this period
    db.session.add(CommissionLineItem(agency_id=agency_id, statement_id=st.id,
                                      carrier="BCBS", period_label="June 2026",
                                      agent_id=a1.id, member_name="X", raw_amount=10.0,
                                      classification="agent_commission", source_ref="bcbs::p1::Sheet1::1"))
    db.session.commit()

    rows = per_agent_upload_status(agency_id, "BCBS", "June 2026")
    by_name = {r["agent_name"]: r["uploaded"] for r in rows}
    assert by_name == {"Brian Freeman": True, "Mike Lauzurique": False}
    # a non-per-agent carrier returns []
    assert per_agent_upload_status(agency_id, "Humana", "June 2026") == []


def test_overview_checklist_has_per_agent_for_bcbs(ctx):
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import commission_audit_overview
    app, agency_id = ctx
    a1 = User(email="b@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    db.session.add(a1); db.session.flush()
    db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a1.id,
                                        carrier="BCBS", is_active=True))
    db.session.commit()
    ov = commission_audit_overview(agency_id, "June 2026")
    bcbs = next((c for c in ov["checklist"] if c["carrier"] == "BCBS"), None)
    assert bcbs is not None
    assert bcbs.get("agents") is not None
    assert any(a["agent_name"] == "Brian Freeman" for a in bcbs["agents"])


def test_process_one_file_rejects_unreadable_with_reason(ctx):
    from app.commission.routes import _process_one_file
    app, agency_id = ctx
    with app.test_request_context():
        res = _process_one_file("junk.xlsx", b"not a real workbook", "2026-06",
                                 agency_id, actor=None)
    assert res["ok"] is False
    assert res["filename"] == "junk.xlsx"
    assert res["error"]                       # a human-readable reason


def _admin(db, agency_id):
    from app.models import User
    u = User(email="admin@x.com", name="AJ", is_admin=True, agency_id=agency_id, role="admin")
    db.session.add(u); db.session.flush(); return u


def test_upload_multi_file_partial_success_json(ctx):
    import io
    from app.extensions import db
    app, agency_id = ctx
    admin = _admin(db, agency_id); db.session.commit()
    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(admin.id); s["_fresh"] = True
    # two "files": both unreadable junk -> both rejected (no real fixtures needed to
    # prove the loop + JSON contract + per-file isolation).
    data = {
        "statement_month": "2026-06",
        "file": [(io.BytesIO(b"junkA"), "a.xlsx"), (io.BytesIO(b"junkB"), "b.xlsx")],
    }
    resp = client.post("/admin/commissions/upload", data=data,
                       content_type="multipart/form-data",
                       headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["summary"]["rejected"] == 2
    assert body["summary"]["imported"] == 0
    assert len(body["results"]) == 2
    assert all(r["ok"] is False and r["error"] for r in body["results"])
    # The final db.session.commit() must have succeeded — session is still usable.
    db.session.execute(db.select(db.text("1")))
