"""
tests/test_uhc_pipeline.py

UHC went live through the normalized pipeline (2026-06-11). These tests cover the
quarantine query helper that surfaces the NEEDS_MANUAL_REVIEW line items (the
~2.3% the parser can't auto-split) for AJ's quarantine tab.
"""
from datetime import date


def _mk_stmt(db, agency, period="May 2026"):
    from app.models import CommissionStatement
    s = CommissionStatement(agency_id=agency.id, carrier="UHC", agent_id=None,
                            period_label=period, filename="uhc.xlsx",
                            statement_date=date(2026, 5, 1))
    db.session.add(s); db.session.flush()
    return s


def _mk_li(db, agency, stmt, *, cls, raw, name, ptype=None, ref):
    from app.models import CommissionLineItem
    li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                            period_label=stmt.period_label, source_ref=ref,
                            member_name=name, raw_amount=raw, split_rate=None,
                            classification=cls, payment_type=ptype)
    db.session.add(li); db.session.flush()
    return li


def test_quarantined_line_items_returns_only_needs_review(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="agent_commission", raw=28.92, name="OK, ONE", ref="uhc::0::1")
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=517.50, name="NEW, ALICE",
               ptype="New", ref="uhc::0::2")
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=0.26, name="DUST, BOB",
               ptype="partd dust", ref="uhc::0::3")
        db.session.commit()

        q = quarantined_line_items(stmt.id, agency.id)
        assert q["count"] == 2
        assert round(q["total"], 2) == round(517.50 + 0.26, 2)
        names = {r["member_name"] for r in q["rows"]}
        assert names == {"NEW, ALICE", "DUST, BOB"}
        # the auto-split row is NOT in the quarantine list
        assert "OK, ONE" not in names


def test_quarantined_line_items_empty_when_none(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="agent_commission", raw=28.92, name="OK, ONE", ref="uhc::0::1")
        db.session.commit()

        q = quarantined_line_items(stmt.id, agency.id)
        assert q["count"] == 0
        assert q["total"] == 0.0
        assert q["rows"] == []


def test_quarantine_page_renders_for_admin(db_session, app, client, agency):
    """The quarantine review page renders end-to-end through the route + template
    (catches context-processor/template regressions, not just the helper)."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        admin = User(name="AJ", email="admin@test.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin); db.session.flush()
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=517.50,
               name="NEW, ALICE", ptype="New", ref="uhc::0::2")
        db.session.commit()
        sid, uid = stmt.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get(f"/admin/commissions/{sid}/quarantine")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "NEW, ALICE" in body
    assert "Quarantine" in body


def test_long_quarantine_action_string_persists(db_session, app, agency):
    """A real UHC quarantine row stores the full Commission Action description
    (~95 chars). It must persist (the column was VARCHAR(32) and broke uploads
    with StringDataRightTruncation — regression guard for migration 026)."""
    from app.extensions import db
    from app.models import CommissionLineItem

    long_action = ("New, DVH Manual Payment, DVH 1000 Plan, 09/01/2025 eff, "
                   "Policy 450396656, written by 6435806 for JANA BENSON, State: NC,")
    assert len(long_action) > 32

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=29.53,
               name="BENSON, JANA", ptype=long_action, ref="uhc::0::30")
        db.session.commit()  # MUST NOT raise StringDataRightTruncation

        li = CommissionLineItem.query.filter_by(statement_id=stmt.id).first()
        assert li.payment_type == long_action  # stored in full, not truncated


def test_betty_riddle_legal_name_resolves_to_betty_marlowe(db_session, app, agency):
    """Betty writes some UHC business under her legal name 'RIDDLE, BETTY B'. It
    must resolve to her portal user (Betty Marlowe), not fall through unmatched."""
    from app.extensions import db
    from app.models import User
    from app.commission.routes import _match_agent_name

    with app.app_context():
        betty = User(name="Betty Marlowe", email="betty@test.com", agency_id=agency.id)
        db.session.add(betty); db.session.flush()
        assert _match_agent_name("RIDDLE, BETTY B") == betty.id
        assert _match_agent_name("Betty Marlowe") == betty.id   # her portal name still works


def test_quarantined_line_items_scoped_to_statement_and_agency(db_session, app, agency):
    """Must not leak quarantine rows from another statement or another agency."""
    from app.extensions import db
    from app.models import Agency
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        other = Agency(name="Other Agency")
        db.session.add(other); db.session.flush()

        s1 = _mk_stmt(db, agency)
        s2 = _mk_stmt(db, agency, period="June 2026")
        _mk_li(db, agency, s1, cls="needs_manual_review", raw=100.0, name="S1", ref="uhc::0::1")
        _mk_li(db, agency, s2, cls="needs_manual_review", raw=200.0, name="S2", ref="uhc::0::1")
        db.session.commit()

        q1 = quarantined_line_items(s1.id, agency.id)
        assert q1["count"] == 1 and q1["rows"][0]["member_name"] == "S1"
        # wrong agency → nothing
        assert quarantined_line_items(s1.id, other.id)["count"] == 0
