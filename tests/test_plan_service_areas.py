import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, Plan, PlanServiceArea


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        p = Plan(agency_id=ag.id, carrier="UHC", cms_plan_id="H5253-041", year=2026,
                 plan_name="Patriot", plan_type="mapd", status="current")
        db.session.add(p); db.session.commit()
        yield app, ag.id, p.id
        db.session.remove(); db.drop_all()


def test_plan_service_area_rows_persist(ctx):
    app, agency_id, pid = ctx
    with app.app_context():
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Cabarrus"))
        db.session.commit()
        rows = PlanServiceArea.query.filter_by(plan_id=pid, agency_id=agency_id).all()
        assert {r.county for r in rows} == {"Mecklenburg", "Cabarrus"}


def test_plan_service_area_unique_constraint(ctx):
    app, agency_id, pid = ctx
    with app.app_context():
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        db.session.commit()
        db.session.add(PlanServiceArea(plan_id=pid, agency_id=agency_id,
                                       state="NC", county="Mecklenburg"))
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()
