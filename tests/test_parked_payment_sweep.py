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


def test_sweep_attaches_humana_via_umid_in_mbi_column(db_session, app):
    """Humana's commission normalizer stores the UMID in PolicyPayment.mbi and the
    PID in PolicyPayment.carrier_member_id (app/commission/normalizers.py
    normalize_humana). The BOB-created Customer.humana_id and the Humana Policy's
    member_id are both the UMID. The sweep must match customer.humana_id against
    PolicyPayment.mbi (not carrier_member_id), and the inner policy lookup must
    resolve via either candidate id."""
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="Humana",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="Humana",
                                     member_name="John Connelly", period_label="May 2026",
                                     commission_action="renewal",
                                     mbi="UMID123", carrier_member_id="PID999",
                                     paid_amount=42.0,
                                     policy_id=None, match_confidence="unmatched",
                                     source_ref="humana::x::0"))
        db.session.flush()

        c = Customer(agency_id=a.id, first_name="John", last_name="Connelly",
                     full_name="John Connelly", humana_id="UMID123")
        db.session.add(c); db.session.flush()
        pol = Policy(agency_id=a.id, carrier="Humana", member_id="UMID123",
                     status="active", customer_id=c.id)
        db.session.add(pol); db.session.flush()

        n = sweep_parked_payments(c, a.id)
        db.session.flush()
        assert n == 1
        pay = PolicyPayment.query.filter_by(source_ref="humana::x::0").first()
        assert pay.policy_id == pol.id
        assert pay.match_confidence == "swept"


def test_sweep_does_not_attach_non_customer_payments(db_session, app):
    """NON_CUSTOMER rows (HRA bonuses, UHC pure-overrides, PARTD dust) are
    deliberately member-less and already paid — they must never be swept onto a
    policy even if they happen to carry an MBI that matches a real customer."""
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.payments import sweep_parked_payments
    with app.app_context():
        a, u = _agency_and_user(db, app)
        stmt = CommissionStatement(agency_id=a.id, carrier="UHC",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=stmt.id, carrier="UHC",
                                     member_name="HRA Bonus", period_label="May 2026",
                                     commission_action="non_customer",
                                     mbi="1AB2C", paid_amount=50.0,
                                     policy_id=None, match_confidence="unmatched",
                                     source_ref="uhc::x::H::0"))
        db.session.flush()
        c = Customer(agency_id=a.id, first_name="Bob", last_name="Jones",
                     full_name="Bob Jones", mbi="1AB2C")
        db.session.add(c); db.session.flush()
        pol = Policy(agency_id=a.id, carrier="UHC", member_id="1AB2C",
                     status="active", customer_id=c.id)
        db.session.add(pol); db.session.flush()

        n = sweep_parked_payments(c, a.id)
        db.session.flush()
        assert n == 0
        pay = PolicyPayment.query.filter_by(source_ref="uhc::x::H::0").first()
        assert pay.policy_id is None
        assert pay.match_confidence == "unmatched"


def test_parked_older_than_excludes_non_customer_rows(db_session, app):
    """NON_CUSTOMER rows are paid, not held — they must not inflate the stale-park
    aging signal even when old and unmatched."""
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
        before = parked_payments_older_than(30, a.id)
        db.session.add(PolicyPayment(agency_id=a.id, statement_id=old.id, carrier="UHC",
                                     member_name="HRA Bonus", period_label="old",
                                     commission_action="non_customer",
                                     mbi="OLDHRA", paid_amount=50.0, policy_id=None,
                                     match_confidence="unmatched",
                                     statement_date=date.today() - timedelta(days=45),
                                     source_ref="uhc::x::H::99"))
        db.session.flush()
        assert parked_payments_older_than(30, a.id) == before


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
