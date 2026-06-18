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
