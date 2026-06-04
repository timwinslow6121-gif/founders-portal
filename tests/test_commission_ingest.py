"""
tests/test_commission_ingest.py

Tests for the commission ingest pipeline: write payments from MemberFact (update-
in-place), fingerprint, and the normalize→resolve→pay flow. SQLite in-memory.
"""
import os
from datetime import date

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def _statement(db, agency, carrier="Devoted"):
    from app.models import CommissionStatement
    s = CommissionStatement(agency_id=agency.id, carrier=carrier,
                            statement_date=date(2026, 5, 1), period_label="May 2026")
    db.session.add(s)
    db.session.flush()
    return s


def test_write_payment_from_fact_inserts_then_updates(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import write_payment_from_fact

    with app.app_context():
        stmt = _statement(db, agency)
        cust = Customer(agency_id=agency.id, first_name="X", last_name="Y", full_name="X Y")
        db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=agency.id, carrier="Devoted", member_id="DGFY27",
                     status="active", customer_id=cust.id)
        db.session.add(pol); db.session.flush()

        fact = MemberFact(carrier="Devoted", full_name="Rene Barger", first_name="Rene",
                          last_name="Barger", carrier_member_id="DGFY27",
                          row_class=RowClass.ENROLLMENT, amount=260.25,
                          effective_date=date(2026, 4, 1))

        p1 = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p1.paid_amount == 260.25
        assert p1.policy_id == pol.id
        assert p1.is_chargeback is False
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == 1

        # Same fact again (re-upload) → UPDATE in place, not a 2nd row
        fact.amount = 270.00
        p2 = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p2.id == p1.id
        assert p2.paid_amount == 270.00
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == 1


def test_write_payment_flags_chargeback_on_negative(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import write_payment_from_fact

    with app.app_context():
        stmt = _statement(db, agency)
        cust = Customer(agency_id=agency.id, first_name="C", last_name="B", full_name="C B")
        db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=agency.id, carrier="Devoted", member_id="DS97W3",
                     status="active", customer_id=cust.id)
        db.session.add(pol); db.session.flush()
        fact = MemberFact(carrier="Devoted", full_name="Elizabeth Bolder",
                          first_name="Elizabeth", last_name="Bolder",
                          carrier_member_id="DS97W3", row_class=RowClass.CHARGEBACK,
                          amount=-347.0)
        p = write_payment_from_fact(fact, stmt, pol, agency.id, agent_user.id)
        db.session.flush()
        assert p.paid_amount == -347.0
        assert p.is_chargeback is True


def test_compute_fingerprint_is_stable_and_sensitive(db_session, app, agency):
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import compute_fingerprint

    facts = [
        MemberFact(carrier="Devoted", full_name="A B", carrier_member_id="1",
                   row_class=RowClass.ENROLLMENT, amount=100.0),
        MemberFact(carrier="Devoted", full_name="C D", carrier_member_id="2",
                   row_class=RowClass.RENEWAL, amount=28.92),
    ]
    fp1 = compute_fingerprint("Devoted", "May 2026", facts)
    fp2 = compute_fingerprint("Devoted", "May 2026", list(facts))
    assert fp1 == fp2                       # stable / order-independent on same data

    # A changed amount → different fingerprint
    facts2 = [facts[0], MemberFact(carrier="Devoted", full_name="C D",
              carrier_member_id="2", row_class=RowClass.RENEWAL, amount=99.99)]
    assert compute_fingerprint("Devoted", "May 2026", facts2) != fp1

    # A different period → different fingerprint
    assert compute_fingerprint("Devoted", "June 2026", facts) != fp1


def test_ingest_statement_devoted_creates_customers_and_payments(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.sheet_loader import load_sheets
    from app.commission.ingest import ingest_statement

    with app.app_context():
        sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()

        result = ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()

        assert Customer.query.filter_by(agency_id=agency.id).count() > 0
        payments = PolicyPayment.query.filter_by(statement_id=stmt.id).all()
        assert len(payments) > 0
        bolder = [p for p in payments if p.carrier_member_id == "DS97W3"]
        assert bolder and bolder[0].is_chargeback is True
        assert result.payments_written == len(payments)
        assert result.customers_created > 0
        assert result.fingerprint


def test_ingest_statement_is_idempotent(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment, CommissionStatement
    from app.commission.sheet_loader import load_sheets
    from app.commission.ingest import ingest_statement

    with app.app_context():
        sheets = load_sheets(os.path.join(FIXTURES, "devoted_sample.xlsx"))
        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()

        ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()
        c1 = Customer.query.filter_by(agency_id=agency.id).count()
        p1 = PolicyPayment.query.filter_by(statement_id=stmt.id).count()
        pol1 = Policy.query.filter_by(agency_id=agency.id).count()

        ingest_statement(stmt, "Devoted", agent_user.id, agency.id, sheets)
        db.session.commit()
        assert Customer.query.filter_by(agency_id=agency.id).count() == c1
        assert PolicyPayment.query.filter_by(statement_id=stmt.id).count() == p1
        assert Policy.query.filter_by(agency_id=agency.id).count() == pol1


def test_statement_has_content_fingerprint_column(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionStatement
    from datetime import date as _d
    with app.app_context():
        s = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                statement_date=_d(2026, 5, 1), period_label="May 2026",
                                content_fingerprint="abc123")
        db.session.add(s); db.session.commit()
        assert s.content_fingerprint == "abc123"


def _login_admin(client, app, agency):
    from app.extensions import db
    from app.models import User
    with app.app_context():
        u = User(email="aj@test.com", name="AJ", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.commit()
        uid = u.id
    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    return uid


def test_route_blocks_exact_duplicate(client, app, agency, db_session):
    _login_admin(client, app, agency)
    from app.models import CommissionStatement
    path = os.path.join(FIXTURES, "devoted_sample.xlsx")

    r1 = client.post("/admin/commissions/upload",
                     data={"file": (open(path, "rb"), "devoted_sample.xlsx"),
                           "statement_month": "2026-05"},
                     content_type="multipart/form-data", follow_redirects=True)
    assert r1.status_code == 200
    with app.app_context():
        n_before = CommissionStatement.query.filter_by(agency_id=agency.id,
                                                       carrier="Devoted").count()
    r2 = client.post("/admin/commissions/upload",
                     data={"file": (open(path, "rb"), "devoted_sample.xlsx"),
                           "statement_month": "2026-05"},
                     content_type="multipart/form-data", follow_redirects=True)
    assert b"already" in r2.data.lower() or b"duplicate" in r2.data.lower()
    with app.app_context():
        n_after = CommissionStatement.query.filter_by(agency_id=agency.id,
                                                      carrier="Devoted").count()
    assert n_after == n_before


def test_ingest_resolves_agent_per_row(db_session, app, agency):
    """Agency-level file: each row's writing agent should own that member's
    customer/AOR/payment, not one statement-level agent."""
    from app.extensions import db
    from app.models import User, Customer, Policy, PolicyPayment, CommissionStatement, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import ingest_statement

    with app.app_context():
        brian = User(email="brian@t.com", name="Brian Freeman", agency_id=agency.id)
        rebekah = User(email="reb@t.com", name="Rebekah Long", agency_id=agency.id)
        uploader = User(email="aj@t.com", name="AJ", is_admin=True, agency_id=agency.id)
        db.session.add_all([brian, rebekah, uploader]); db.session.flush()

        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()

        facts = [
            MemberFact(carrier="Devoted", full_name="Member One", first_name="Member",
                       last_name="One", carrier_member_id="M1", writing_agent_raw="Brian Freeman",
                       row_class=RowClass.ENROLLMENT, amount=260.25, effective_date=date(2026,4,1),
                       source_ref="devoted::Agent Portion::1"),
            MemberFact(carrier="Devoted", full_name="Member Two", first_name="Member",
                       last_name="Two", carrier_member_id="M2", writing_agent_raw="Rebekah Long",
                       row_class=RowClass.ENROLLMENT, amount=260.25, effective_date=date(2026,4,1),
                       source_ref="devoted::Agent Portion::2"),
        ]

        # monkeypatch the normalizer for this carrier to return our crafted facts
        import app.commission.ingest as ingest_mod
        orig = ingest_mod.NORMALIZERS.get("Devoted")
        ingest_mod.NORMALIZERS["Devoted"] = lambda sheets: facts
        try:
            def resolver(raw):
                from app.models import User as U
                u = U.query.filter(U.agency_id == agency.id, U.name == raw).first()
                return u.id if u else None
            ingest_statement(stmt, "Devoted", uploader.id, agency.id, {}, agent_resolver=resolver)
            db.session.commit()
        finally:
            if orig is not None:
                ingest_mod.NORMALIZERS["Devoted"] = orig

        m1 = Customer.query.filter_by(agency_id=agency.id, last_name="One").first()
        m2 = Customer.query.filter_by(agency_id=agency.id, last_name="Two").first()
        assert m1.primary_agent_id == brian.id      # row 1 → Brian
        assert m2.primary_agent_id == rebekah.id     # row 2 → Rebekah
        # payments attribute per-row too
        p1 = PolicyPayment.query.filter_by(statement_id=stmt.id, carrier_member_id="M1").first()
        p2 = PolicyPayment.query.filter_by(statement_id=stmt.id, carrier_member_id="M2").first()
        assert p1.agent_id == brian.id
        assert p2.agent_id == rebekah.id


def test_ingest_falls_back_to_statement_agent_when_no_resolver(db_session, app, agency, agent_user):
    """Backward compatible: no agent_resolver → statement-level agent_id used for all."""
    from app.extensions import db
    from app.models import Customer, CommissionStatement
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.ingest import ingest_statement
    import app.commission.ingest as ingest_mod

    with app.app_context():
        stmt = CommissionStatement(agency_id=agency.id, carrier="Devoted",
                                   statement_date=date(2026, 5, 1), period_label="May 2026")
        db.session.add(stmt); db.session.flush()
        facts = [MemberFact(carrier="Devoted", full_name="Solo One", first_name="Solo",
                            last_name="One", carrier_member_id="S1",
                            writing_agent_raw="Nobody Matches",
                            row_class=RowClass.ENROLLMENT, amount=10.0,
                            source_ref="devoted::Agent Portion::1")]
        orig = ingest_mod.NORMALIZERS.get("Devoted")
        ingest_mod.NORMALIZERS["Devoted"] = lambda sheets: facts
        try:
            ingest_statement(stmt, "Devoted", agent_user.id, agency.id, {})
            db.session.commit()
        finally:
            if orig is not None:
                ingest_mod.NORMALIZERS["Devoted"] = orig
        c = Customer.query.filter_by(agency_id=agency.id, last_name="One").first()
        assert c.primary_agent_id == agent_user.id   # fell back to statement agent
