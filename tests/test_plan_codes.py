def test_policy_and_plan_new_columns_exist(app, db_session):
    from app.models import Policy, Plan
    with app.app_context():
        p = Policy(carrier="Humana", member_id="M1", contract_code="H1036-335-001",
                   plan_year=2026, status="active")
        db_session.add(p); db_session.flush()
        got = Policy.query.filter_by(member_id="M1").first()
        assert got.contract_code == "H1036-335-001"
        assert got.plan_year == 2026
        pl = Plan(agency_id=1, carrier="Humana", plan_name="X", year=2026,
                  plan_type="mapd", needs_review=True)
        db_session.add(pl); db_session.flush()
        assert Plan.query.filter_by(plan_name="X").first().needs_review is True
