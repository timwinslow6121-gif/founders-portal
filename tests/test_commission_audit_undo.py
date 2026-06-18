def test_revision_model_persists(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItemRevision
    with app.app_context():
        rev = CommissionLineItemRevision(
            agency_id=agency.id, line_item_id=1, statement_id=1,
            action="resolve", user_id=None,
            before_json='{"classification":"needs_manual_review"}',
            after_json='{"classification":"agent_commission"}',
            sibling_source_ref="uhc::0::5::ovr", undone=False)
        db.session.add(rev); db.session.commit()
        got = CommissionLineItemRevision.query.first()
        assert got.action == "resolve"
        assert got.undone is False
        assert got.sibling_source_ref == "uhc::0::5::ovr"


def test_snapshot_line_captures_mutable_fields(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import _snapshot_line
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New", agent_id=7)
        db.session.add(li); db.session.flush()
        snap = _snapshot_line(li)
        assert snap == {"classification": "needs_manual_review", "raw_amount": 33.51,
                        "split_rate": None, "agent_id": 7, "payment_type": "New"}


def test_resolve_writes_a_revision_with_before_state(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionLineItemRevision
    from app.commission.ledger import resolve_quarantine_line
    import json
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        rev = CommissionLineItemRevision.query.filter_by(line_item_id=li.id).first()
        assert rev is not None
        assert rev.action == "resolve"
        assert rev.user_id == 3
        before = json.loads(rev.before_json)
        assert before["classification"] == "needs_manual_review"
        assert before["raw_amount"] == 33.51
        # the override sibling it created is recorded for undo
        assert rev.sibling_source_ref == "uhc::0::5::ovr"
        # invariant: agent remainder + override == original raw
        assert round(li.raw_amount + 4.59, 2) == 33.51
