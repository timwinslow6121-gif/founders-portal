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
                        "split_rate": None, "agent_id": 7, "payment_type": "New",
                        "manually_adjusted": False}


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


def test_undo_restores_exact_prior_state_and_removes_override(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, undo_last_change
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        # sanity: it was resolved + an override sibling exists
        assert li.classification == "agent_commission"
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 1

        ok = undo_last_change(li, user_id=3)
        db.session.commit()
        assert ok is True
        # line restored to EXACT prior state
        assert li.classification == "needs_manual_review"
        assert li.raw_amount == 33.51
        assert li.split_rate is None
        assert li.payment_type == "New"
        # the override sibling the resolve created is gone
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 0


def test_undo_after_re_resolve_restores_prior_override(db_session, app, agency):
    """A line gets resolved TWICE (creating an ::ovr sibling, then re-resolving
    it to a different override amount). Undoing the SECOND resolve must restore
    the sibling to its value from BEFORE that resolve (10), not delete it —
    otherwise Sigma raw_amount silently changes (money lost)."""
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, undo_last_change
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::7", raw_amount=100.0, split_rate=None,
            classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()

        # resolve #1: override=10 -> line.raw=90, ovr.raw=10 (Sum=100)
        resolve_quarantine_line(li, agent_id=7, override_amount=10.0,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        assert li.raw_amount == 90.0
        ovr = CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::7::ovr").first()
        assert ovr is not None and ovr.raw_amount == 10.0

        # resolve #2 (re-resolve): override=20 -> line.raw=70, ovr.raw=20
        resolve_quarantine_line(li, agent_id=7, override_amount=20.0,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        assert li.raw_amount == 70.0
        db.session.refresh(ovr)
        assert ovr.raw_amount == 20.0

        # undo the re-resolve (resolve #2)
        ok = undo_last_change(li, user_id=3)
        db.session.commit()
        assert ok is True

        # line restored to its post-resolve#1 state
        assert li.raw_amount == 90.0

        # the sibling must be RESTORED to 10 (its value before resolve#2),
        # NOT deleted -- this is the bug under test.
        sib = CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::7::ovr").first()
        assert sib is not None, "override sibling was wrongly deleted on undo"
        assert sib.raw_amount == 10.0

        # the money invariant: Sum raw_amount across line + sibling == original 100
        assert round(li.raw_amount + sib.raw_amount, 2) == 100.0


def test_undo_returns_false_when_nothing_to_undo(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import undo_last_change
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::9", raw_amount=10.0, split_rate=0.55,
            classification="agent_commission", payment_type="renewal")
        db.session.add(li); db.session.flush()
        assert undo_last_change(li, user_id=3) is False


def test_edit_line_split_enforces_sum_invariant(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionLineItemRevision
    from app.commission.ledger import edit_line_split
    with app.app_context():
        # a row currently all agent_commission ($33.51), no override sibling
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=0.55,
            classification="agent_commission", payment_type="renewal", agent_id=7)
        db.session.add(li); db.session.flush()

        # correct the split to 28.92 agent + 4.59 override (sums to 33.51)
        edit_line_split(li, agent_amount=28.92, override_amount=4.59,
                        agent_id=7, split_rate=0.55, user_id=3)
        db.session.commit()
        assert li.raw_amount == 28.92
        ovr = CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").first()
        assert ovr is not None and ovr.raw_amount == 4.59
        assert ovr.classification == "founders_override"
        rev = CommissionLineItemRevision.query.filter_by(
            line_item_id=li.id, action="edit").first()
        assert rev is not None

        # an edit that BREAKS the sum is rejected
        import pytest
        with pytest.raises(ValueError):
            edit_line_split(li, agent_amount=20.00, override_amount=4.59,
                            agent_id=7, split_rate=0.55, user_id=3)


def test_undo_after_edit_restores_state(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import edit_line_split, undo_last_change
    with app.app_context():
        # all agent_commission, no sibling override
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::5", raw_amount=33.51, split_rate=0.55,
            classification="agent_commission", payment_type="renewal", agent_id=7)
        db.session.add(li); db.session.flush()

        edit_line_split(li, agent_amount=28.92, override_amount=4.59,
                        agent_id=7, split_rate=0.55, user_id=3)
        db.session.commit()
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 1

        ok = undo_last_change(li, user_id=3)
        db.session.commit()
        assert ok is True
        assert li.raw_amount == 33.51
        assert li.classification == "agent_commission"
        # the sibling didn't exist before the edit -> undo removes it
        assert CommissionLineItem.query.filter_by(
            statement_id=1, source_ref="uhc::0::5::ovr").count() == 0


def test_edit_stores_agent_amount_as_final_payout_and_undo_restores(db_session, app, agency):
    """A manual edit stores AJ's agent_amount as the FINAL payout (split_rate=1.0,
    manually_adjusted=True) so split_breakdown reproduces his exact dollars in the
    recap — and undo restores the TRUE prior state (the snapshot must capture it
    before the edit mutates it)."""
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import edit_line_split, undo_last_change, split_breakdown
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::6", raw_amount=33.51, split_rate=0.55,
            classification="agent_commission", payment_type="renewal", agent_id=7)
        db.session.add(li); db.session.flush()

        edit_line_split(li, agent_amount=28.92, override_amount=4.59,
                        agent_id=7, user_id=3)
        db.session.commit()
        # the agent's entered $ is the FINAL payout (rate forced to 1.0, flagged)
        assert li.split_rate == 1.0
        assert li.manually_adjusted is True
        payout, _ = split_breakdown(li)
        assert round(payout, 2) == 28.92   # exactly what AJ entered, not 28.92×0.55

        ok = undo_last_change(li, user_id=3)
        db.session.commit()
        assert ok is True
        assert li.split_rate == 0.55   # RESTORED to the original
        assert li.raw_amount == 33.51
        assert li.classification == "agent_commission"


def test_resolve_override_sibling_inherits_customer_id(db_session, app, agency):
    """Quirk #4: the ::ovr Founders-override sibling created by resolve_quarantine_line
    must carry the parent's customer_id (it's the SAME member) — else it becomes an
    orphaned line item the payment_without_customer radar flags."""
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::77", raw_amount=33.51, split_rate=None,
            classification="needs_manual_review", payment_type="New",
            customer_id=4242)
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59,
                                split_rate=0.55, user_id=3)
        db.session.commit()
        ovr = CommissionLineItem.query.filter_by(source_ref="uhc::0::77::ovr").first()
        assert ovr is not None
        assert ovr.customer_id == 4242          # inherits parent's customer, not NULL


def test_edit_override_sibling_inherits_and_repairs_customer_id(db_session, app, agency):
    """Quirk #4: edit_line_split's ::ovr sibling must inherit the parent's customer_id
    on create, AND repair a previously-NULL sibling on a later edit."""
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import edit_line_split
    with app.app_context():
        li = CommissionLineItem(
            agency_id=agency.id, statement_id=1, carrier="UHC",
            source_ref="uhc::0::88", raw_amount=50.0, split_rate=0.55,
            classification="hra_bonus", payment_type="hra", customer_id=999)
        db.session.add(li); db.session.flush()
        # edit creates an override sibling
        edit_line_split(li, agent_amount=26.25, override_amount=23.75,
                        agent_id=7, user_id=3)
        db.session.commit()
        ovr = CommissionLineItem.query.filter_by(source_ref="uhc::0::88::ovr").first()
        assert ovr is not None
        assert ovr.customer_id == 999

        # simulate a previously-orphaned sibling, then re-edit -> repaired
        ovr.customer_id = None
        db.session.commit()
        edit_line_split(li, agent_amount=30.0, override_amount=20.0,
                        agent_id=7, user_id=3)
        db.session.commit()
        ovr2 = CommissionLineItem.query.filter_by(source_ref="uhc::0::88::ovr").first()
        assert ovr2.customer_id == 999          # repaired on re-edit
