import datetime
import pytest


@pytest.fixture
def ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()


def _plan(db, agency_id, ptype="mapd"):
    from app.models import Plan
    p = Plan(agency_id=agency_id, carrier="Aetna", cms_plan_id="H3146-006", year=2026,
             plan_name="Value Plus", plan_type=ptype, status="current")
    db.session.add(p); db.session.flush(); return p


def _cust(db, agency_id):
    from app.models import Customer
    c = Customer(agency_id=agency_id, first_name="Bobby", last_name="Aderhold",
                 full_name="Bobby Aderhold", mbi="6CM1RV8NW05")
    db.session.add(c); db.session.flush(); return c


def _pol(db, agency_id, cust, plan, member_id, mbi=None, batch=None, eff="2025-01-01"):
    from app.models import Policy
    p = Policy(agency_id=agency_id, carrier="Aetna", member_id=member_id, mbi=mbi,
               plan_id=plan.id, status="active", customer_id=cust.id,
               effective_date=datetime.date.fromisoformat(eff), import_batch_id=batch)
    db.session.add(p); db.session.flush(); return p


def _pay(db, policy):
    import datetime
    from app.models import PolicyPayment, CommissionStatement
    st = CommissionStatement(agency_id=policy.agency_id, carrier="Aetna",
                             period_label="May 2026",
                             statement_date=datetime.date(2026, 5, 1))
    db.session.add(st); db.session.flush()
    pp = PolicyPayment(policy_id=policy.id, agency_id=policy.agency_id, statement_id=st.id,
                       carrier="Aetna", period_label="May 2026", member_name="Bobby Aderhold",
                       commission_action="renewal", paid_amount=100.0, is_chargeback=False)
    db.session.add(pp); db.session.flush(); return pp


def test_merges_same_plan_keeps_member_id_and_mbi(ctx):
    """Two active policies, same customer + plan_id + eff date. Survivor keeps
    member_id = the carrier policy id (NG-id) AND mbi = the person's MBI (both kept).
    The payment-bearing row survives; the other's payments reattach."""
    from app.extensions import db
    from app.models import Policy, PolicyPayment
    app, agency_id = ctx
    pl = _plan(db, agency_id)
    c = _cust(db, agency_id)
    mbi_row = _pol(db, agency_id, c, pl, member_id="6CM1RV8NW05", mbi="6CM1RV8NW05", batch=39)
    ngid_row = _pol(db, agency_id, c, pl, member_id="NG101350365000", mbi="6CM1RV8NW05")
    _pay(db, ngid_row)          # the money is on the NG-id row
    db.session.commit()
    from scripts.dedupe_duplicate_policies import dedupe
    res = dedupe(agency_id, apply=True)
    assert res["merged_pairs"] == 1
    survivors = Policy.query.filter_by(customer_id=c.id, status="active").all()
    assert len(survivors) == 1                       # collapsed to ONE
    s = survivors[0]
    assert s.member_id == "NG101350365000"           # carrier policy id kept (money row)
    assert s.mbi == "6CM1RV8NW05"                    # person MBI kept
    assert PolicyPayment.query.filter_by(policy_id=s.id).count() == 1   # payment reattached


def test_survivor_fills_mbi_from_loser(ctx):
    """If the surviving (payment/carrier-id) row lacks the MBI, take it from the merged row
    so the person identifier isn't lost."""
    from app.extensions import db
    from app.models import Policy
    app, agency_id = ctx
    pl = _plan(db, agency_id); c = _cust(db, agency_id)
    ngid = _pol(db, agency_id, c, pl, member_id="NG101350365000", mbi=None)  # no MBI, but survives (has pmt)
    _pay(db, ngid)
    mbi_row = _pol(db, agency_id, c, pl, member_id="6CM1RV8NW05", mbi="6CM1RV8NW05", batch=39)
    db.session.commit()
    from scripts.dedupe_duplicate_policies import dedupe
    dedupe(agency_id, apply=True)
    s = Policy.query.filter_by(customer_id=c.id, status="active").one()
    assert s.member_id == "NG101350365000" and s.mbi == "6CM1RV8NW05"


def test_holds_different_effective_date(ctx):
    """Same plan but DIFFERENT effective date = possible re-enrollment, NOT auto-merged."""
    from app.extensions import db
    from app.models import Policy
    app, agency_id = ctx
    pl = _plan(db, agency_id); c = _cust(db, agency_id)
    _pol(db, agency_id, c, pl, member_id="A1", eff="2024-01-01")
    _pol(db, agency_id, c, pl, member_id="A2", eff="2025-01-01")
    db.session.commit()
    from scripts.dedupe_duplicate_policies import dedupe
    res = dedupe(agency_id, apply=True)
    assert res["merged_pairs"] == 0 and res["held_diff_eff"] == 1
    assert Policy.query.filter_by(customer_id=c.id, status="active").count() == 2  # untouched


def test_dry_run_writes_nothing(ctx):
    from app.extensions import db
    from app.models import Policy
    app, agency_id = ctx
    pl = _plan(db, agency_id); c = _cust(db, agency_id)
    _pol(db, agency_id, c, pl, member_id="6CM1RV8NW05", mbi="6CM1RV8NW05", batch=39)
    _pol(db, agency_id, c, pl, member_id="NG1", mbi="6CM1RV8NW05")
    db.session.commit()
    from scripts.dedupe_duplicate_policies import dedupe
    res = dedupe(agency_id, apply=False)
    assert res["merged_pairs"] == 1
    assert Policy.query.filter_by(customer_id=c.id, status="active").count() == 2  # not merged
