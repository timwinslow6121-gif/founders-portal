from datetime import date
import io
import os
from unittest.mock import patch, call
import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


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


def test_per_agent_upload_status_includes_uploaded_at(ctx):
    from datetime import datetime
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, CommissionStatement,
                            CommissionLineItem)
    from app.commission.recap import per_agent_upload_status
    app, agency_id = ctx
    a1 = User(email="b@x.com", name="Brian Freeman", agency_id=agency_id, role="agent")
    a2 = User(email="m@x.com", name="Mike Lauzurique", agency_id=agency_id, role="agent")
    db.session.add_all([a1, a2]); db.session.flush()
    for a in (a1, a2):
        db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=a.id,
                                            carrier="BCBS", is_active=True))
    st = CommissionStatement(agency_id=agency_id, carrier="BCBS",
                             statement_date=date(2026, 6, 1), period_label="June 2026")
    db.session.add(st); db.session.flush()
    li = CommissionLineItem(agency_id=agency_id, statement_id=st.id, carrier="BCBS",
                            period_label="June 2026", agent_id=a1.id, member_name="X",
                            raw_amount=10.0, classification="agent_commission",
                            source_ref="bcbs::p1::Sheet1::1")
    db.session.add(li); db.session.commit()

    rows = per_agent_upload_status(agency_id, "BCBS", "June 2026")
    by_name = {r["agent_name"]: r for r in rows}
    assert by_name["Brian Freeman"]["uploaded"] is True
    # uploaded_at is an ISO string (not a datetime) so the template can embed it in
    # JSON and the JS new Date() parse is reliable cross-browser.
    assert isinstance(by_name["Brian Freeman"]["uploaded_at"], str)
    assert "2026-" in by_name["Brian Freeman"]["uploaded_at"]
    assert by_name["Mike Lauzurique"]["uploaded"] is False
    assert by_name["Mike Lauzurique"]["uploaded_at"] is None


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


def _setup_bcbs_agents(db, agency_id):
    """Create the minimal users the BCBS fixture references so the ingest resolves agents."""
    from app.models import User
    # bcbs_sample.xlsx contains rows attributed to 'BRIAN FREEMAN'.
    brian = User(email="brianfreeman@x.com", name="Brian Freeman",
                 agency_id=agency_id, role="agent")
    db.session.add(brian)
    db.session.flush()
    return brian


def _do_good_bad_upload(client, admin_id, agency_id, good_bytes, good_name, bad_bytes, bad_name):
    """POST good + bad files in one multipart request; return (resp, body)."""
    from app.extensions import db
    data = {
        "statement_month": "2026-06",
        "file": [
            (io.BytesIO(good_bytes), good_name),
            (io.BytesIO(bad_bytes), bad_name),
        ],
    }
    with client.session_transaction() as s:
        s["_user_id"] = str(admin_id); s["_fresh"] = True
    resp = client.post("/admin/commissions/upload", data=data,
                       content_type="multipart/form-data",
                       headers={"X-Requested-With": "XMLHttpRequest"})
    return resp, resp.get_json()


def test_upload_good_and_bad_file_isolation(ctx):
    """Prove savepoint isolation: a good file's committed savepoint SURVIVES a later
    bad file's nested.rollback().  The good file's CommissionStatement +
    CommissionLineItem rows must persist after the final db.session.commit(), even
    though the bad file's savepoint was rolled back.

    Also tests the reverse order (bad-then-good) to confirm neither ordering
    corrupts the result.
    """
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem
    app, agency_id = ctx

    # Add SESSION_COOKIE_SECURE=False so the test client's http:// session round-trips.
    app.config.update(SESSION_COOKIE_SECURE=False, REMEMBER_COOKIE_SECURE=False)

    bcbs_bytes = open(os.path.join(FIXTURES, "bcbs_sample.xlsx"), "rb").read()
    junk_bytes = b"not a workbook"

    # ── Setup: admin user + agent names the BCBS fixture references ──────────
    admin = _admin(db, agency_id)
    _setup_bcbs_agents(db, agency_id)
    db.session.commit()
    admin_id = admin.id

    client = app.test_client()

    # ── ORDER 1: good (BCBS) then bad (junk) ─────────────────────────────────
    resp, body = _do_good_bad_upload(
        client, admin_id, agency_id,
        bcbs_bytes, "bcbs_sample.xlsx",
        junk_bytes, "junk.xlsx",
    )
    assert resp.status_code == 200, f"Upload returned {resp.status_code}"
    assert body["summary"]["imported"] == 1, f"Expected 1 import, got: {body['summary']}"
    assert body["summary"]["rejected"] == 1, f"Expected 1 reject, got: {body['summary']}"

    results_by_file = {r["filename"]: r for r in body["results"]}
    assert results_by_file["bcbs_sample.xlsx"]["ok"] is True, \
        f"BCBS result not ok: {results_by_file['bcbs_sample.xlsx']}"
    assert results_by_file["junk.xlsx"]["ok"] is False, \
        f"Junk should have failed: {results_by_file['junk.xlsx']}"
    assert results_by_file["junk.xlsx"].get("error"), "Junk file should have an error message"

    # The good file's rows must have PERSISTED past the final commit.
    with app.app_context():
        bcbs_stmts = CommissionStatement.query.filter_by(
            agency_id=agency_id, carrier="BCBS"
        ).all()
        assert len(bcbs_stmts) >= 1, \
            "BCBS CommissionStatement did not survive the bad file's savepoint rollback"
        stmt_id = bcbs_stmts[0].id
        li_count = CommissionLineItem.query.filter_by(
            agency_id=agency_id, statement_id=stmt_id
        ).count()
        assert li_count >= 1, \
            f"BCBS CommissionLineItems missing (count={li_count}) — good-file data was wiped"

    # The junk file must have left NO statement.
    with app.app_context():
        total_stmts = CommissionStatement.query.filter_by(agency_id=agency_id).count()
        assert total_stmts == len(bcbs_stmts), \
            f"Junk file created an unexpected statement (total={total_stmts})"

    # ── Cleanup between the two order tests ──────────────────────────────────
    with app.app_context():
        CommissionLineItem.query.filter_by(agency_id=agency_id).delete(synchronize_session=False)
        CommissionStatement.query.filter_by(agency_id=agency_id).delete(synchronize_session=False)
        db.session.commit()

    # ── ORDER 2: bad (junk) then good (BCBS) ─────────────────────────────────
    resp2, body2 = _do_good_bad_upload(
        client, admin_id, agency_id,
        junk_bytes, "junk.xlsx",
        bcbs_bytes, "bcbs_sample.xlsx",
    )
    assert resp2.status_code == 200
    assert body2["summary"]["imported"] == 1, f"Bad-then-good: expected 1 import, got: {body2['summary']}"
    assert body2["summary"]["rejected"] == 1, f"Bad-then-good: expected 1 reject, got: {body2['summary']}"

    with app.app_context():
        bcbs_stmts2 = CommissionStatement.query.filter_by(
            agency_id=agency_id, carrier="BCBS"
        ).all()
        assert len(bcbs_stmts2) >= 1, \
            "BCBS CommissionStatement missing in bad-then-good order"
        li_count2 = CommissionLineItem.query.filter_by(
            agency_id=agency_id, statement_id=bcbs_stmts2[0].id
        ).count()
        assert li_count2 >= 1, \
            f"BCBS CommissionLineItems missing in bad-then-good order (count={li_count2})"


def test_upload_good_then_ingest_failing_file_preserves_good(ctx):
    """Regression test for opus C1: a bare db.session.rollback() inside
    _ingest_normalized_upload's except block wiped ALL prior savepoints when a
    file that parsed OK failed *during ingest* (inside ingest_statement /
    persist_line_items).  This test forces exactly that failure path.

    Strategy: upload two files in one POST.  File 1 is the real bcbs_sample.xlsx
    (parses + ingests normally).  File 2 is also the real bcbs_sample.xlsx (so it
    passes the parse/carrier-detect step and reaches _ingest_normalized_upload),
    but we monkeypatch `app.commission.routes.ingest_statement` so that its SECOND
    call raises RuntimeError("boom") — simulating a DB constraint or any ingest-
    stage failure.

    The dup-guard (find_duplicate_statement) would short-circuit before ingest on the
    second identical file, so we also patch it to always return None — ensuring the
    second file reaches ingest_statement where it raises.

    Pre-fix behaviour: the bare db.session.rollback() in the ingest except block
    unwound the ENTIRE outer transaction (destroying file 1's already-committed
    savepoint), then nested.rollback() raised ResourceClosedError → the route 500'd.

    Post-fix behaviour: the rollback line is gone; the loop's nested.rollback() owns
    the unwind; the outer transaction survives; the route returns 200 with
    imported=1, rejected=1; file 1's rows are still in the DB.

    NOTE: on SQLite the ResourceClosedError does NOT propagate (SQLite's savepoint
    model is more lenient than Postgres), so this test may not 500 pre-fix on SQLite.
    The data-loss assertion (CommissionStatement/LineItem survival) is the definitive
    check; the status=200 check is a secondary signal. The test is still kept because
    it documents and locks the contract against regression.
    """
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem

    app, agency_id = ctx
    app.config.update(SESSION_COOKIE_SECURE=False, REMEMBER_COOKIE_SECURE=False)

    bcbs_bytes = open(os.path.join(FIXTURES, "bcbs_sample.xlsx"), "rb").read()

    admin = _admin(db, agency_id)
    _setup_bcbs_agents(db, agency_id)
    db.session.commit()

    call_count = {"n": 0}

    # Import the real ingest_statement so we can call it normally the first time.
    import app.commission.ingest as _ingest_mod
    real_ingest_statement = _ingest_mod.ingest_statement

    def ingest_statement_boom_on_second(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return real_ingest_statement(*args, **kwargs)
        raise RuntimeError("simulated ingest failure for C1 regression test")

    client = app.test_client()
    with client.session_transaction() as s:
        s["_user_id"] = str(admin.id); s["_fresh"] = True

    data = {
        "statement_month": "2026-06",
        "file": [
            (io.BytesIO(bcbs_bytes), "bcbs_sample.xlsx"),   # file 1 — should succeed
            (io.BytesIO(bcbs_bytes), "bcbs_sample_v2.xlsx"),  # file 2 — ingest will raise
        ],
    }

    # Patch both ingest_statement (to raise on 2nd call) and find_duplicate_statement
    # (to return None always so file 2 is NOT short-circuited by the dup guard —
    # which would prevent it from reaching ingest_statement at all).
    with patch("app.commission.routes.ingest_statement",
               side_effect=ingest_statement_boom_on_second), \
         patch("app.commission.routes.find_duplicate_statement", return_value=None):
        resp = client.post(
            "/admin/commissions/upload",
            data=data,
            content_type="multipart/form-data",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    # The route must NOT 500 (pre-fix: ResourceClosedError escapes and 500s on Postgres).
    assert resp.status_code == 200, (
        f"Route returned {resp.status_code} — pre-fix this was a 500 from "
        f"ResourceClosedError after the bare session.rollback() closed the transaction"
    )

    body = resp.get_json()
    assert body is not None, "Expected JSON response body"
    assert body["summary"]["imported"] == 1, \
        f"Expected 1 import (file 1), got: {body['summary']}"
    assert body["summary"]["rejected"] == 1, \
        f"Expected 1 rejection (file 2 ingest failure), got: {body['summary']}"

    # Money-correctness proof: file 1's rows must have SURVIVED the failed ingest of
    # file 2.  Pre-fix the bare rollback() destroyed them (data loss).
    with app.app_context():
        bcbs_stmts = CommissionStatement.query.filter_by(
            agency_id=agency_id, carrier="BCBS"
        ).all()
        assert len(bcbs_stmts) >= 1, (
            "BCBS CommissionStatement was destroyed — "
            "the bare db.session.rollback() wiped the outer transaction"
        )
        li_count = CommissionLineItem.query.filter_by(
            agency_id=agency_id, statement_id=bcbs_stmts[0].id
        ).count()
        assert li_count >= 1, (
            f"BCBS CommissionLineItems were wiped (count={li_count}) — "
            "bare session.rollback() destroyed file 1's committed savepoint data"
        )


def test_ledger_split_lookup_works_without_request_context(ctx):
    """_ledger_split_lookup must resolve the split from the passed-in agency_id,
    NOT the global current_user. current_user is only bound inside a request; the
    ingest (and any script/re-import) runs it with just an app context. Reaching for
    current_user.agency_id there raised 'NoneType has no attribute agency_id' and
    crashed the whole upload. Regression guard for the Devoted-June ingest crash."""
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.routes import _ledger_split_lookup
    app, agency_id = ctx
    u = User(email="reb@x.com", name="Rebekah Long", agency_id=agency_id, role="agent")
    db.session.add(u); db.session.flush()
    db.session.add(AgentCarrierContract(agency_id=agency_id, agent_id=u.id,
                                        carrier="Devoted", split_rate=0.50, is_active=True))
    db.session.flush()
    # No request context here → current_user is unavailable. Must still work.
    rate = _ledger_split_lookup("LONG, REBEKAH", "Devoted", agency_id)
    assert rate == 0.50
    # unknown agent → falls back to an active Devoted contract (0.50), else 0.55
    assert _ledger_split_lookup("NOBODY NAMED THIS", "Devoted", agency_id) == 0.50
    assert _ledger_split_lookup("NOBODY", "Aetna", agency_id) == 0.55
