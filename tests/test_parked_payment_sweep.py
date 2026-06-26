from datetime import date


def _agency_and_user(db, app):
    from app.models import Agency, User
    a = Agency(name="T"); db.session.add(a); db.session.flush()
    u = User(name="Agent", email="a@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
    return a, u


def test_sweep_attaches_all_parked_for_matching_mbi(db_session, app):
    """BOB creates the customer + their Policy; both parked payments for that MBI
    attach by getting policy_id set (PolicyPayment has no customer_id column —
    linkage is via the policy)."""
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="UHC",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        # two parked payments, same MBI, not yet linked to any policy
        for i in range(2):
            db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="UHC",
                                         member_name="Bob Jones", period_label="May 2026",
                                         commission_action="renewal",
                                         mbi="1AB2C", paid_amount=50.0,
                                         policy_id=None, match_confidence="unmatched",
                                         source_ref=f"uhc::x::S::{i}"))
        db.session.flush()
        # BOB now creates the customer AND their policy (member_id == the MBI for UHC)
        c = Customer(agency_id=a.id, first_name="Bob", last_name="Jones",
                     full_name="Bob Jones", mbi="1AB2C")
        db.session.add(c); db.session.flush()
        pol = Policy(agency_id=a.id, carrier="UHC", member_id="1AB2C",
                     status="active", customer_id=c.id)
        db.session.add(pol); db.session.flush()

        n = sweep_parked_payments(c, a.id)
        db.session.flush()
        assert n == 2
        # attached == both now carry the customer's policy_id
        assert PolicyPayment.query.filter_by(policy_id=pol.id).count() == 2
        assert PolicyPayment.query.filter_by(policy_id=None).count() == 0
        # and they trace to the customer through the policy
        for pay in PolicyPayment.query.filter_by(policy_id=pol.id).all():
            assert pay.policy.customer_id == c.id
            assert pay.match_confidence != "unmatched"


def test_sweep_is_idempotent(db_session, app):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    from datetime import date
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="UHC",
                                   statement_date=date(2026,5,1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="UHC",
                                     member_name="Z Z", period_label="May 2026",
                                     commission_action="renewal",
                                     mbi="ZZ9", paid_amount=10.0,
                                     policy_id=None, match_confidence="unmatched",
                                     source_ref="uhc::x::S::0"))
        c = Customer(agency_id=a.id, first_name="Z", last_name="Z", full_name="Z Z", mbi="ZZ9")
        db.session.add(c); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="ZZ9",
                              status="active", customer_id=c.id)); db.session.flush()
        assert sweep_parked_payments(c, a.id) == 1
        db.session.flush()


def test_parked_older_than_counts_aged_holds(db_session, app):
    from app.extensions import db
    from app.models import PolicyPayment, CommissionStatement
    from app.commission.payments import parked_payments_older_than
    from datetime import date, timedelta
    with app.app_context():
        a, u = _agency_and_user(db, app)
        old = CommissionStatement(agency_id=a.id, carrier="UHC",
                                  statement_date=date.today() - timedelta(days=45),
                                  period_label="old")
        db.session.add(old); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=old.id, carrier="UHC",
                                     member_name="Old Hold", period_label="old",
                                     commission_action="renewal",
                                     mbi="OLD1", paid_amount=10.0, policy_id=None,
                                     match_confidence="unmatched",
                                     statement_date=date.today() - timedelta(days=45),
                                     source_ref="uhc::x::S::99"))
        db.session.flush()
        assert parked_payments_older_than(30, a.id) >= 1

        # A fresh/recent parked payment should NOT count toward the >30d total.
        before = parked_payments_older_than(30, a.id)
        recent = CommissionStatement(agency_id=a.id, carrier="UHC",
                                     statement_date=date.today(), period_label="recent")
        db.session.add(recent); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=recent.id, carrier="UHC",
                                     member_name="Fresh Hold", period_label="recent",
                                     commission_action="renewal",
                                     mbi="NEW1", paid_amount=10.0, policy_id=None,
                                     match_confidence="unmatched",
                                     statement_date=date.today(),
                                     source_ref="uhc::x::S::100"))
        db.session.flush()
        assert parked_payments_older_than(30, a.id) == before
