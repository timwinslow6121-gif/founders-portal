"""Tier rules, in the spec's evaluation order (SPEC 5.2)."""
import datetime as dt
import pytest

TODAY = dt.date(2026, 10, 20)


@pytest.fixture
def cfg(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        c = PipelineConfig(agency_id=agency.id, sep_days=30,
                           shp_enabled=True,
                           shp_start=dt.date(2026, 10, 12),
                           shp_end=dt.date(2026, 10, 30))
        db.session.add(c)
        db.session.commit()
        # Refresh before returning: commit() expires the instance, and the
        # fixture's app_context exits before the test body reads an attribute.
        # Every other fixture in conftest.py does the same.
        db.session.refresh(c)
        return c


def _state(db, agency, customer, **kw):
    from app.models import PipelineState
    ps = PipelineState(agency_id=agency.id, customer_id=customer.id, **kw)
    db.session.add(ps)
    db.session.commit()
    return ps


def test_manual_override_beats_every_rule(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True, tier_override=3,
                    tier_override_note="he called already")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 3
        assert got.reason_code == "override"


def test_shp_pending_is_tier_1_with_days_left(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True)
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 1
        assert got.reason_code == "shp_pending"
        assert got.days_left == 10


def test_shp_confirmed_drops_out_of_tier_1(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, shp_flag=True,
                    shp_confirmed_at=dt.datetime(2026, 10, 15))
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "unrated"


def test_unrated_plan_is_tier_2_so_nobody_is_skipped(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer)
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "unrated"


def test_lead_urgency_comes_from_the_date_not_the_category(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead",
                    sep_end=dt.date(2026, 11, 5), sep_reason="Employer coverage ends")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 1
        assert got.reason_code == "sep_urgent"
        assert got.days_left == 16


def test_lead_with_no_date_is_tier_2_and_says_so(db_session, app, agency, customer, cfg):
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead")
        got = tier_for(customer, ps, cfg, today=TODAY)
        assert got.tier == 2
        assert got.reason_code == "no_deadline"


def test_lead_far_out_is_tier_2_until_sep_days_widens(db_session, app, agency, customer, cfg):
    """SPEC acceptance check 5: raising sep_days raises the Tier 1 count."""
    from app.extensions import db
    from app.pipeline.triage import tier_for
    with app.app_context():
        ps = _state(db, agency, customer, track="lead", sep_end=dt.date(2026, 12, 1))
        assert tier_for(customer, ps, cfg, today=TODAY).tier == 2
        cfg.sep_days = 60
        db.session.commit()
        assert tier_for(customer, ps, cfg, today=TODAY).tier == 1
