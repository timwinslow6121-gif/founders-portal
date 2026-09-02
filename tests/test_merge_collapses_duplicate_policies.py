"""
tests/test_merge_collapses_duplicate_policies.py

Merging two duplicate customers moves BOTH their policies onto one person --
which is exactly what CREATES a duplicate policy pair. Tim merged 46 duplicate
customers on 2026-09-01 and 46 duplicate policy pairs appeared behind them
(Tiwana Burch holding HumanaChoice PPO H5525-070 twice), needing a second
cleanup pass.

The two rows are one enrollment keyed two ways -- the BOB's id ('H76593494')
and the commission file's internal id ('409620038') -- with no shared MBI, so
neither ingest nor the merge could match them.

merge_customers must finish the job: after collapsing the people, collapse any
same-plan active policies it just brought together. Same conservative rule as
the standalone script -- identical effective dates, no term date, and never
when both rows carry payments (that means the carrier is paying two policies).
"""


def _setup(app, agency, *, eff_same=True, term=False, pay_both=False):
    from datetime import date
    from app.extensions import db
    from app.models import (Customer, CommissionStatement, Plan, Policy,
                            PolicyPayment, User)
    with app.app_context():
        u = User(email="m@t.com", name="M", is_admin=True, agency_id=agency.id)
        stmt = CommissionStatement(agency_id=agency.id, carrier="Humana",
                                   statement_date=date(2026, 8, 1))
        db.session.add(stmt)
        plan = Plan(agency_id=agency.id, carrier="Humana", year=2026,
                    plan_name="HumanaChoice PPO", plan_type="mapd",
                    cms_plan_id="H5525-070")
        db.session.add_all([u, plan]); db.session.flush()

        keep = Customer(agency_id=agency.id, first_name="Tiwana", last_name="Burch",
                        full_name="Tiwana Burch", dob=date(1955, 3, 2))
        lose = Customer(agency_id=agency.id, first_name="Tiwana", last_name="Burch",
                        full_name="Tiwana Burch", dob=date(1955, 3, 2))
        db.session.add_all([keep, lose]); db.session.flush()

        # BOB-sourced row on the keeper
        pa = Policy(agency_id=agency.id, carrier="Humana", member_id="H76593494",
                    plan_name="HumanaChoice PPO", status="active",
                    customer_id=keep.id, plan_id=plan.id, import_batch_id=51,
                    effective_date=date(2026, 4, 1), full_name="Tiwana Burch")
        # commission-sourced row on the loser
        pb = Policy(agency_id=agency.id, carrier="Humana", member_id="409620038",
                    plan_name="HumanaChoice PPO", status="active",
                    customer_id=lose.id, plan_id=plan.id,
                    effective_date=date(2026, 4, 1) if eff_same else date(2024, 1, 1),
                    term_date=date(2026, 7, 1) if term else None,
                    full_name="Tiwana Burch")
        db.session.add_all([pa, pb]); db.session.flush()

        db.session.add(PolicyPayment(agency_id=agency.id, carrier="Humana",
                                     statement_id=stmt.id, policy_id=pb.id,
                                     period_label="August 2026", member_name="Tiwana Burch",
                                     commission_action="renewal",
                                     paid_amount=28.91))
        if pay_both:
            db.session.add(PolicyPayment(agency_id=agency.id, carrier="Humana",
                                         statement_id=stmt.id, policy_id=pa.id,
                                         period_label="August 2026", member_name="Tiwana Burch",
                                     commission_action="renewal",
                                     paid_amount=28.91))
        db.session.commit()
        return keep.id, lose.id, pa.id, pb.id, u.id


def _active(app, agency, cid):
    from app.models import Policy
    with app.app_context():
        return Policy.query.filter_by(agency_id=agency.id, customer_id=cid,
                                      status="active").all()


def test_merge_collapses_the_duplicate_policy_it_creates(app, agency, db_session):
    from app.extensions import db
    from app.customers import merge_customers
    from app.models import PolicyPayment, User
    keep, lose, pa, pb, uid = _setup(app, agency)
    with app.app_context():
        r = merge_customers(keep, [lose], agency.id, User.query.get(uid))
        db.session.commit()
        assert r["ok"], r.get("error")
    pols = _active(app, agency, keep)
    assert len(pols) == 1, f"customer left holding {len(pols)} copies of one plan"
    assert pols[0].id == pa, "survivor should be the BOB-sourced row"
    with app.app_context():
        # the loser's payment must follow, not vanish
        assert PolicyPayment.query.filter_by(policy_id=pa).count() == 1


def test_differing_effective_dates_are_left_alone(app, agency, db_session):
    """A different date could be a genuine re-enrollment — leave it for a human."""
    from app.extensions import db
    from app.customers import merge_customers
    from app.models import User
    keep, lose, pa, pb, uid = _setup(app, agency, eff_same=False)
    with app.app_context():
        merge_customers(keep, [lose], agency.id, User.query.get(uid))
        db.session.commit()
    assert len(_active(app, agency, keep)) == 2


def test_a_termed_row_is_left_alone(app, agency, db_session):
    from app.extensions import db
    from app.customers import merge_customers
    from app.models import User
    keep, lose, pa, pb, uid = _setup(app, agency, term=True)
    with app.app_context():
        merge_customers(keep, [lose], agency.id, User.query.get(uid))
        db.session.commit()
    # a row carrying a term date must be LEFT ALONE — a term then re-enrollment
    # into the same plan is a real sequence, not a duplicate.
    assert len(_active(app, agency, keep)) == 2


def test_two_paid_policies_are_never_collapsed(app, agency, db_session):
    """If BOTH rows carry payments the carrier is paying two policies — not a
    duplicate, and merging would hide real money."""
    from app.extensions import db
    from app.customers import merge_customers
    from app.models import User
    keep, lose, pa, pb, uid = _setup(app, agency, pay_both=True)
    with app.app_context():
        merge_customers(keep, [lose], agency.id, User.query.get(uid))
        db.session.commit()
    assert len(_active(app, agency, keep)) == 2
