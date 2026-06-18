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
