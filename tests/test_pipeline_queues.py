"""Queue assignment. Exclusivity is structural, not per-predicate (SPEC 6.1)."""
import datetime as dt
import pytest

TODAY = dt.date(2026, 10, 20)


@pytest.fixture
def cfg(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        c = PipelineConfig(agency_id=agency.id, sep_days=30, shp_enabled=True,
                           shp_start=dt.date(2026, 10, 12), shp_end=dt.date(2026, 10, 30),
                           stall_contact_days=5, stall_deciding_days=3,
                           stall_submitted_days=10)
        db.session.add(c)
        db.session.commit()
        # Refresh before returning: commit() expires the instance and the
        # fixture's app_context exits before the test body reads an attribute.
        # Every fixture in conftest.py does the same.
        db.session.refresh(c)
        return c


def _state(db, agency, customer, **kw):
    from app.models import PipelineState
    ps = PipelineState(agency_id=agency.id, customer_id=customer.id, **kw)
    db.session.add(ps)
    db.session.commit()
    return ps


def test_state_retiree_with_appointment_today_lands_in_shp_only(db_session, app, agency, customer, cfg):
    """The exact prototype bug: Charles Starnes was in BOTH shp and today."""
    from app.extensions import db
    from app.models import Appointment
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, stage="scheduled")
        db.session.add(Appointment(agency_id=agency.id, customer_id=customer.id,
                                   starts_at=dt.datetime(2026, 10, 20, 14, 0)))
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) == "shp"


def test_every_customer_lands_in_at_most_one_queue(db_session, app, agency, customer, cfg):
    """queue_for returns a single id by construction -- this asserts the shape."""
    from app.extensions import db
    from app.pipeline.queues import queue_for, QUEUES
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, stage="contact", attempts=0)
        q = queue_for(customer, ps, cfg, TODAY)
        assert q in {qid for qid, _, _ in QUEUES}


def test_stalled_contact_needs_two_attempts_and_five_days(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import stalled_reason
    with app.app_context():
        ps = _state(db, agency, customer, stage="contact", attempts=2,
                    first_try_at=dt.datetime(2026, 10, 10))
        assert stalled_reason(ps, cfg, TODAY) is not None
        ps.attempts = 1
        db.session.commit()
        assert stalled_reason(ps, cfg, TODAY) is None


def test_callfirst_requires_tier_1_and_no_attempts(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, stage="contact", attempts=0, tier_override=1)
        assert queue_for(customer, ps, cfg, TODAY) == "callfirst"
        ps.tier_override = 3
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) is None


def test_deceased_customer_is_in_no_queue(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        customer.deceased_date = dt.date(2026, 10, 1)
        ps = _state(db, agency, customer, stage="contact", attempts=0, tier_override=1)
        db.session.commit()
        assert queue_for(customer, ps, cfg, TODAY) is None


def test_done_customer_is_in_no_queue(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.queues import queue_for
    with app.app_context():
        ps = _state(db, agency, customer, stage="done", outcome="enrolled")
        assert queue_for(customer, ps, cfg, TODAY) is None
