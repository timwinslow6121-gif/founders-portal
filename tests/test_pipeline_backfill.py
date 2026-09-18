"""Backfill: one PipelineState per living customer, idempotent."""
import datetime as dt


def test_backfill_creates_one_state_per_living_customer(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.models import PipelineState
    with app.app_context():
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 1
        ps = PipelineState.query.filter_by(customer_id=customer.id).one()
        assert ps.stage == "contact"
        assert ps.track == "renewal"


def test_backfill_is_idempotent(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    with app.app_context():
        run(apply=True, agency_id=agency.id)
        second = run(apply=True, agency_id=agency.id)
        assert second["created"] == 0
        assert second["skipped_existing"] == 1


def test_backfill_skips_deceased(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.models import Customer
    from app.extensions import db
    with app.app_context():
        # The `customer` fixture object belongs to a session that has since been
        # removed, so mutating it directly writes nothing. Re-attach first.
        c = db.session.get(Customer, customer.id)
        c.deceased_date = dt.date(2026, 9, 1)
        db.session.commit()
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 0
        assert res["skipped_deceased"] == 1


def test_dry_run_writes_nothing(db_session, app, agency, customer):
    from scripts.backfill_pipeline_state import run
    from app.models import PipelineState
    with app.app_context():
        res = run(apply=False, agency_id=agency.id)
        assert res["created"] == 1
        assert PipelineState.query.count() == 0


def test_deceased_with_existing_state_counts_once(db_session, app, agency, customer):
    """A customer who is BOTH deceased and already has a row must be counted in
    exactly one bucket, never both -- otherwise the tallies overstate the book."""
    from scripts.backfill_pipeline_state import run
    from app.models import Customer, PipelineState
    from app.extensions import db
    with app.app_context():
        db.session.add(PipelineState(agency_id=agency.id, customer_id=customer.id))
        c = db.session.get(Customer, customer.id)
        c.deceased_date = dt.date(2026, 9, 1)
        db.session.commit()
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 0
        total = res["skipped_existing"] + res["skipped_deceased"]
        assert total == 1, f"counted twice: {res}"
        assert res["skipped_existing"] == 1


def test_backfill_is_agency_scoped(db_session, app, agency, customer):
    """A customer in another agency is never touched -- a cross-tenant write."""
    from scripts.backfill_pipeline_state import run
    from app.models import Agency, Customer, PipelineState
    from app.extensions import db
    with app.app_context():
        other = Agency(name="Other Agency")
        db.session.add(other)
        db.session.commit()
        db.session.add(Customer(first_name="Jane", last_name="Roe",
                                full_name="Jane Roe", agency_id=other.id,
                                source="test"))
        db.session.commit()
        res = run(apply=True, agency_id=agency.id)
        assert res["created"] == 1
        assert PipelineState.query.count() == 1
        assert PipelineState.query.one().customer_id == customer.id
