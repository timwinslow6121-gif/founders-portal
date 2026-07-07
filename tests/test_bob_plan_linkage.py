from datetime import date

def _rec(**kw):
    base = {"carrier": "Humana", "member_id": "HM1", "mbi": "8QV9Q10TC36",
            "first_name": "A", "last_name": "B", "full_name": "A B",
            "plan_name": "HUMANA GOLD PLUS HMO POS H1036-335", "plan_type": "MAPD",
            "effective_date": date(2024, 1, 1), "term_date": None, "dob": None,
            "phone": "", "county": "", "agent_id": "", "status": "active"}
    base.update(kw); return base

def test_bob_row_links_to_seeded_bucket_sets_code_and_year(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    with app.app_context():
        bucket = Plan(agency_id=agency.id, carrier="Humana", cms_plan_id="H1036-335",
                      year=2026, plan_name="Gold Plus", plan_type="MA", status="current")
        db.session.add(bucket)
        batch = ImportBatch(agency_id=agency.id, carrier="Humana", filename="h.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        with db.session.begin_nested():
            _import_bob_row(_rec(), batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="HM1").first()
        assert pol.plan_id == bucket.id
        assert pol.contract_code == "H1036-335"
        assert pol.plan_year == 2026                # import year, not eff-date 2024

def test_bob_row_with_no_bucket_stays_null_and_is_recorded(db_session, app, agency, agent_user):
    """A row whose plan has no seeded bucket keeps plan_id NULL and is added to the
    review list — NO Plan is auto-created."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Plan
    from app.upload import _import_bob_row
    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="Humana", filename="h.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()
        review = []
        with db.session.begin_nested():
            _import_bob_row(_rec(member_id="HM2", plan_name="HUMANA MYSTERY H9999-999"),
                            batch, agency.id, agent_user.id, date.today(), [],
                            plan_year=2026, plan_review=review)
        db.session.commit()
        pol = Policy.query.filter_by(agency_id=agency.id, member_id="HM2").first()
        assert pol.plan_id is None
        assert Plan.query.filter_by(cms_plan_id="H9999-999").count() == 0   # not created
        assert any("H9999-999" in (r.get("plan_name") or "") for r in review)
