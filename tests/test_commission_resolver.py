"""
tests/test_commission_resolver.py

Tests for the commission→customer resolver: crosswalk, MBI reuse, stub-once,
carrier-switch interval, rapid_disenroll, suggest-link. SQLite in-memory via
conftest fixtures.
"""
import pytest
from datetime import date


def test_new_orm_columns_and_match_suggestion_model(db_session, app, agency):
    from app.models import Customer, Policy, MatchSuggestion
    from app.extensions import db

    with app.app_context():
        c = Customer(
            agency_id=agency.id, first_name="A", last_name="B", full_name="A B",
            stub=True, source="commission_import",
        )
        db.session.add(c)
        db.session.flush()
        p = Policy(
            agency_id=agency.id, carrier="BCBS", member_id="106815011",
            rapid_disenroll=True, commission_split_flag="no_contract",
            customer_id=c.id,
        )
        db.session.add(p)
        db.session.flush()
        ms = MatchSuggestion(
            agency_id=agency.id, suggested_customer_id=c.id,
            confidence="name_dob", status="pending",
            source_member_fact_json="{}",
        )
        db.session.add(ms)
        db.session.commit()

        assert c.stub is True
        assert c.source == "commission_import"
        assert p.rapid_disenroll is True
        assert p.commission_split_flag == "no_contract"
        assert p.customer_id == c.id
        assert ms.status == "pending"
        assert ms.confidence == "name_dob"


def _seed_customer_with_policy(db, agency, agent, *, carrier, member_id, mbi=None,
                               first="Jane", last="Doe"):
    from app.models import Customer, Policy
    c = Customer(agency_id=agency.id, first_name=first, last_name=last,
                 full_name=f"{first} {last}", mbi=mbi, primary_agent_id=agent.id,
                 source="bob")
    db.session.add(c)
    db.session.flush()
    p = Policy(agency_id=agency.id, carrier=carrier, member_id=member_id, mbi=mbi,
              full_name=f"{first} {last}", status="active", agent_id=agent.id,
              customer_id=c.id)
    db.session.add(p)
    db.session.flush()
    return c, p


def test_crosswalk_reuses_existing_customer(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="BCBS", member_id="106815011",
            first="Brenda", last="Allen",
        )
        fact = MemberFact(
            carrier="BCBS", full_name="Allen,Brenda M", first_name="Brenda",
            last_name="Allen", carrier_member_id="106815011",
            row_class=RowClass.RENEWAL, amount=28.91,
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id          # reused, not new
        assert result.created_customer is False
        assert result.match_path == "crosswalk"
        assert result.customer.stub is False        # existing real customer untouched


def test_mbi_match_reuses_customer_and_creates_policy(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Bobby", last_name="Aderhold",
                     full_name="Bobby Aderhold", mbi="6CM1RV8NW05",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c)
        db.session.flush()

        fact = MemberFact(
            carrier="Aetna", full_name="ADERHOLD R,BOBBY", first_name="Bobby",
            last_name="Aderhold", mbi="6CM1RV8NW05", carrier_member_id="NG101350365000",
            plan_contract="H3146", plan_pbp="006", row_class=RowClass.RENEWAL, amount=28.92,
            effective_date=date(2026, 5, 1),
        )
        result = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                                  source="commission_import")

        assert result.customer.id == c.id
        assert result.match_path == "mbi"
        assert result.created_customer is False
        assert result.created_policy is True
        assert result.policy.carrier == "Aetna"
        assert result.policy.member_id == "NG101350365000"
        assert result.policy.customer_id == c.id


def test_stub_created_once_then_crosswalk_relinks(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="BCBS", full_name="Newby,Sam", first_name="Sam", last_name="Newby",
            carrier_member_id="106999999", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 4, 1),
        )
        # First upload → stub created
        r1 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r1.created_customer is True
        assert r1.match_path == "stub"
        assert r1.customer.stub is True
        assert r1.customer.source == "commission_import"
        db.session.commit()

        # Second upload of the SAME fact → crosswalk re-link, NO new stub
        r2 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r2.created_customer is False
        assert r2.match_path == "crosswalk"
        assert r2.customer.id == r1.customer.id

        # Exactly one customer + one policy exist for this member
        assert Customer.query.filter_by(agency_id=agency.id).count() == 1
        assert Policy.query.filter_by(agency_id=agency.id, member_id="106999999").count() == 1


def test_rapid_disenroll_flag_set_when_under_90_days(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="Devoted", full_name="Elizabeth Bolder", first_name="Elizabeth",
            last_name="Bolder", carrier_member_id="DS97W3", mbi="1X57MJ7FA64",
            row_class=RowClass.CHARGEBACK, amount=-347.0,
            effective_date=date(2026, 1, 1), term_date=date(2026, 3, 31),  # < 90d
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")
        assert r.policy.rapid_disenroll is True
        assert "rapid_disenroll" in r.actions


def test_carrier_switch_terms_old_policy_and_opens_new_interval(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Dorothy", last_name="Smith",
                     full_name="Dorothy Smith", mbi="9ZZ9ZZ9ZZ99",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c); db.session.flush()
        old = Policy(agency_id=agency.id, carrier="Humana", member_id="PID123",
                     mbi="9ZZ9ZZ9ZZ99", status="active", agent_id=agent_user.id,
                     customer_id=c.id, effective_date=date(2025, 1, 1))
        db.session.add(old); db.session.flush()

        fact = MemberFact(
            carrier="BCBS", full_name="Smith,Dorothy", first_name="Dorothy",
            last_name="Smith", carrier_member_id="106800000", mbi="9ZZ9ZZ9ZZ99",
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        assert r.customer.id == c.id
        db.session.refresh(old)
        assert old.status == "termed"
        assert "carrier_switch" in r.actions
        intervals = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="BCBS").all()
        assert len(intervals) == 1
        assert intervals[0].end_date is None


def test_suggest_link_creates_stub_and_suggestion_no_automerge(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, MatchSuggestion
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        existing = Customer(agency_id=agency.id, first_name="Mark", last_name="Brown",
                            full_name="Mark Brown", dob=date(1950, 4, 2),
                            primary_agent_id=agent_user.id, source="bob")
        db.session.add(existing); db.session.flush()

        fact = MemberFact(
            carrier="BCBS", full_name="Brown,Mark", first_name="Mark", last_name="Brown",
            dob=date(1950, 4, 2), carrier_member_id="106777777", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        assert r.created_customer is True
        assert r.customer.id != existing.id
        assert r.customer.stub is True
        assert r.match_path == "suggest_link"
        assert "match_suggestion" in r.actions

        ms = MatchSuggestion.query.filter_by(agency_id=agency.id, status="pending").first()
        assert ms is not None
        assert ms.suggested_customer_id == existing.id
        assert ms.stub_customer_id == r.customer.id
        assert ms.confidence == "name_dob"


def test_mbi_only_fact_is_idempotent_no_duplicate_policy(db_session, app, agency, agent_user):
    """An MBI-only fact (no carrier_member_id, e.g. UHC BOB row) must not create a
    duplicate policy on re-upload — crosswalk must find the MBI-keyed policy."""
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        fact = MemberFact(
            carrier="UHC", full_name="Jo Test", first_name="Jo", last_name="Test",
            mbi="TESTMBI999", carrier_member_id=None,
            row_class=RowClass.RENEWAL, amount=10.0, effective_date=date(2026, 1, 1),
        )
        r1 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="bob")
        db.session.commit()
        r2 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="bob")
        db.session.commit()  # must NOT raise IntegrityError

        assert Policy.query.filter_by(agency_id=agency.id, carrier="UHC").count() == 1
        assert Customer.query.filter_by(agency_id=agency.id).count() == 1
        assert r2.policy.id == r1.policy.id


def test_get_customer_policies_finds_fk_linked_bcbs_no_mbi(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, Policy
    from app.customers import get_customer_policies

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Sam", last_name="Newby",
                     full_name="Sam Newby", mbi=None, stub=True,
                     source="commission_import", primary_agent_id=agent_user.id)
        db.session.add(c); db.session.flush()
        p = Policy(agency_id=agency.id, carrier="BCBS", member_id="106999999",
                   mbi=None, status="active", agent_id=agent_user.id, customer_id=c.id,
                   full_name="Sam Newby")
        db.session.add(p); db.session.commit()

        policies = get_customer_policies(c)
        assert any(pol.carrier == "BCBS" and pol.member_id == "106999999"
                   for pol in policies)


def test_bob_two_step_flow_no_duplicate_policy(db_session, app, agency, agent_user):
    """Reproduces the REAL BOB upload: outer loop adds the Policy (customer_id NULL),
    THEN _upsert_customer_from_policy runs. Must NOT create a duplicate policy."""
    from app.extensions import db
    from app.models import Customer, Policy
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        # Step 1: outer loop creates the canonical policy with NO customer_id
        policy = Policy(agency_id=agency.id, agent_id=agent_user.id, carrier="UHC",
                        member_id="9726", mbi="MBINEW001", first_name="New",
                        last_name="Member", full_name="New Member", status="active")
        db.session.add(policy)
        db.session.flush()
        # Step 2: the customer upsert (delegates to resolver)
        rec = {"carrier": "UHC", "mbi": "MBINEW001", "member_id": "9726",
               "first_name": "New", "last_name": "Member", "full_name": "New Member",
               "plan_name": "UHC Dual Complete", "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()  # MUST NOT raise IntegrityError

        assert Policy.query.filter_by(agency_id=agency.id, carrier="UHC",
                                      member_id="9726").count() == 1
        c = Customer.query.filter_by(mbi="MBINEW001", agency_id=agency.id).first()
        assert c is not None
        # the outer-loop policy got adopted + linked
        db.session.refresh(policy)
        assert policy.customer_id == c.id


def test_bob_aor_plan_name_preserved(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Customer, CustomerAorHistory
    from app.upload import _upsert_customer_from_policy

    with app.app_context():
        rec = {"carrier": "UHC", "mbi": "MBIPLAN01", "member_id": "P1",
               "first_name": "Plan", "last_name": "Named", "full_name": "Plan Named",
               "plan_name": "UHC Dual Complete HMO", "effective_date": date(2026, 1, 1)}
        _upsert_customer_from_policy(rec, agent_user.id, None, agency.id)
        db.session.commit()
        c = Customer.query.filter_by(mbi="MBIPLAN01", agency_id=agency.id).first()
        aor = CustomerAorHistory.query.filter_by(customer_id=c.id, carrier="UHC").first()
        assert aor is not None
        assert aor.plan_name == "UHC Dual Complete HMO"


def test_humana_rows_without_carrier_id_or_mbi_do_not_collide(db_session, app, agency, agent_user):
    """Real Humana files have rows with neither PID nor MBI. They must each get a
    unique policy member_id (via source_ref), not collide on empty string."""
    from app.extensions import db
    from app.models import Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        f1 = MemberFact(carrier="Humana", full_name="Helms Teressa", first_name="Teressa",
                        last_name="Helms", mbi=None, carrier_member_id=None,
                        row_class=RowClass.RENEWAL, amount=29.94,
                        source_ref="humana::CommissionData_1::226")
        f2 = MemberFact(carrier="Humana", full_name="Bollinger Annette", first_name="Annette",
                        last_name="Bollinger", mbi=None, carrier_member_id=None,
                        row_class=RowClass.RENEWAL, amount=23.66,
                        source_ref="humana::CommissionData_1::227")
        resolve_customer(f1, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        resolve_customer(f2, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()  # must NOT raise IntegrityError
        # two distinct policies, keyed by their source_refs
        assert Policy.query.filter_by(agency_id=agency.id, carrier="Humana").count() == 2
        mids = {p.member_id for p in Policy.query.filter_by(carrier="Humana").all()}
        assert mids == {"humana::CommissionData_1::226", "humana::CommissionData_1::227"}


def test_humana_no_id_row_is_idempotent(db_session, app, agency, agent_user):
    from app.extensions import db
    from app.models import Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    with app.app_context():
        f = MemberFact(carrier="Humana", full_name="Helms Teressa", first_name="Teressa",
                       last_name="Helms", mbi=None, carrier_member_id=None,
                       row_class=RowClass.RENEWAL, amount=29.94,
                       source_ref="humana::CommissionData_1::226")
        resolve_customer(f, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()
        resolve_customer(f, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()
        assert Policy.query.filter_by(agency_id=agency.id, carrier="Humana").count() == 1
