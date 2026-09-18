"""Pipeline model shape — migration 046."""
import datetime as dt


def test_pipeline_state_defaults_and_scoping(db_session, app, agency, customer):
    from app.models import PipelineState
    from app.extensions import db
    with app.app_context():
        ps = PipelineState(customer_id=customer.id, agency_id=agency.id)
        db.session.add(ps)
        db.session.commit()
        db.session.refresh(ps)
        assert ps.stage == "contact"
        assert ps.track == "renewal"
        assert ps.outcome is None
        assert ps.attempts == 0
        assert ps.stage_since is not None


def test_touch_is_append_only_with_unique_external_id(db_session, app, agency, customer, agent_user):
    from app.models import Touch
    from app.extensions import db
    import sqlalchemy.exc
    with app.app_context():
        t = Touch(customer_id=customer.id, agency_id=agency.id, agent_id=agent_user.id,
                  level="reached", channel="call", direction="in",
                  occurred_at=dt.datetime(2026, 10, 20, 9, 0), external_id="quo-abc")
        db.session.add(t)
        db.session.commit()
        dupe = Touch(customer_id=customer.id, agency_id=agency.id, agent_id=agent_user.id,
                     level="reached", channel="call", direction="in",
                     occurred_at=dt.datetime(2026, 10, 20, 9, 1), external_id="quo-abc")
        db.session.add(dupe)
        try:
            db.session.commit()
            assert False, "duplicate external_id must be rejected"
        except sqlalchemy.exc.IntegrityError:
            db.session.rollback()


def test_sar_rule_and_plan_rating(db_session, app, agency):
    from app.models import SarRule, PlanRating, Plan
    from app.extensions import db
    with app.app_context():
        p = Plan(agency_id=agency.id, carrier="Humana", plan_name="Giveback",
                 year=2027, plan_type="mapd", cms_plan_id="H5525-035")
        db.session.add(p)
        db.session.commit()
        db.session.add(SarRule(agency_id=agency.id, plan_id=p.id, county="Cabarrus", state="NC"))
        db.session.add(PlanRating(agency_id=agency.id, plan_id=p.id, rating=1))
        db.session.commit()
        assert SarRule.query.filter_by(plan_id=p.id).count() == 1
        assert PlanRating.query.filter_by(plan_id=p.id).one().rating == 1


def test_pipeline_config_is_single_row_per_agency(db_session, app, agency):
    from app.models import PipelineConfig
    from app.extensions import db
    with app.app_context():
        cfg = PipelineConfig(agency_id=agency.id)
        db.session.add(cfg)
        db.session.commit()
        db.session.refresh(cfg)
        assert cfg.sep_days == 30
        assert cfg.stall_contact_days == 5
        assert cfg.stall_deciding_days == 3
        assert cfg.stall_submitted_days == 10
        assert cfg.rules_status == "draft"
