import pytest
from app import create_app
from app.extensions import db
from app.models import Agency, Plan, PlanServiceArea
from scripts.seed_plan_service_areas import seed_service_areas_from_rows


def _row(contract, plan, county, state="NC", year="2026"):
    return {"Contract Year": year, "State Territory Abbreviation": state,
            "County Name": county, "Contract ID": contract, "Plan ID": plan}


@pytest.fixture
def ctx():
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, LOGIN_DISABLED=True)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        # A Part C plan that IS in the CSV, and a Medigap plan that is NOT (no cms id).
        db.session.add(Plan(agency_id=ag.id, carrier="UHC", cms_plan_id="H5253-041",
                            year=2026, plan_name="Patriot", plan_type="mapd", status="current"))
        db.session.add(Plan(agency_id=ag.id, carrier="Aetna", cms_plan_id=None,
                            plan_letter="G", year=2026, plan_name="Medigap Plan G",
                            plan_type="medigap", status="current"))
        db.session.commit()
        yield app, ag.id


def test_seed_loads_counties_and_skips_sentinel_and_noncarried(ctx):
    app, agency_id = ctx
    rows = [
        _row("H5253", "041", "Mecklenburg"),
        _row("H5253", "041", "Cabarrus"),
        _row("H5253", "041", "All Counties"),   # sentinel — must be skipped
        _row("H5253", "041", ""),                # blank — must be skipped
        _row("H9999", "001", "Wake"),            # not carried — must be skipped
    ]
    with app.app_context():
        report = seed_service_areas_from_rows(rows, agency_id, apply=True, states=("NC",))
        assert report["plans_matched"] == 1
        assert report["counties_loaded"] == 2          # Mecklenburg + Cabarrus only
        p = Plan.query.filter_by(cms_plan_id="H5253-041").first()
        got = {r.county for r in PlanServiceArea.query.filter_by(plan_id=p.id).all()}
        assert got == {"Mecklenburg", "Cabarrus"}


def test_seed_is_idempotent(ctx):
    app, agency_id = ctx
    rows = [_row("H5253", "041", "Mecklenburg"), _row("H5253", "041", "Cabarrus")]
    with app.app_context():
        seed_service_areas_from_rows(rows, agency_id, apply=True)
        seed_service_areas_from_rows(rows, agency_id, apply=True)   # second run
        p = Plan.query.filter_by(cms_plan_id="H5253-041").first()
        assert PlanServiceArea.query.filter_by(plan_id=p.id).count() == 2  # no dupes


def test_seed_dry_run_writes_nothing(ctx):
    app, agency_id = ctx
    rows = [_row("H5253", "041", "Mecklenburg")]
    with app.app_context():
        report = seed_service_areas_from_rows(rows, agency_id, apply=False)
        assert report["plans_matched"] == 1
        assert PlanServiceArea.query.count() == 0
