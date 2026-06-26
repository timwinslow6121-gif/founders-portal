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


def test_unmatched_commission_row_parks_on_every_resolve_no_stub_ever(db_session, app, agency, agent_user):
    """Commission path is ID-only match-or-park: a carrier_member_id with NO
    existing customer/policy to attach to must PARK, not create a stub —
    replaces the old new_strong-then-crosswalk-relink behavior (which assumed
    the commission path creates new customers; it no longer does, see Task 1).
    Re-resolving the same unmatched fact parks again every time — it can never
    self-heal into a stub+crosswalk pair because nothing was ever created."""
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
        r1 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r1.created_customer is False
        assert r1.match_path == "parked"
        assert r1.customer is None
        db.session.commit()

        # Second resolve of the SAME fact → parks again, still no customer/policy.
        r2 = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        assert r2.created_customer is False
        assert r2.match_path == "parked"
        assert r2.customer is None

        # No customer or policy ever materialized for this member.
        assert Customer.query.filter_by(agency_id=agency.id).count() == 0
        assert Policy.query.filter_by(agency_id=agency.id, member_id="106999999").count() == 0


def test_rapid_disenroll_flag_set_when_under_90_days(db_session, app, agency, agent_user):
    """rapid_disenroll still applies on the commission path's ID-attach branch
    (an existing customer matched by MBI), not on a parked/no-match row."""
    from app.extensions import db
    from app.models import Customer
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Elizabeth", last_name="Bolder",
                     full_name="Elizabeth Bolder", mbi="1X57MJ7FA64",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c); db.session.flush()

        fact = MemberFact(
            carrier="Devoted", full_name="Elizabeth Bolder", first_name="Elizabeth",
            last_name="Bolder", carrier_member_id="DS97W3", mbi="1X57MJ7FA64",
            row_class=RowClass.CHARGEBACK, amount=-347.0,
            effective_date=date(2026, 1, 1), term_date=date(2026, 3, 31),  # < 90d
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")
        assert r.match_path == "mbi"
        assert r.customer.id == c.id
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


def test_name_dob_only_match_parks_no_stub_on_commission_path(db_session, app, agency, agent_user):
    """A name+DOB near-match candidate exists, but the fact carries no MBI/
    carrier_member_id that resolves to an existing Policy/Customer — the
    commission path never matches on name, so this PARKS (no stub, no
    suggest-link). Replaces the old suggest_link-creates-a-stub behavior,
    which was a BOB-path-only tier prior to this task."""
    from app.extensions import db
    from app.models import Customer, MatchSuggestion
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        existing = Customer(agency_id=agency.id, first_name="Mark", last_name="Brown",
                            full_name="Mark Brown", dob=date(1950, 4, 2),
                            primary_agent_id=agent_user.id, source="bob")
        db.session.add(existing); db.session.flush()
        before = Customer.query.count()

        fact = MemberFact(
            carrier="BCBS", full_name="Brown,Mark", first_name="Mark", last_name="Brown",
            dob=date(1950, 4, 2), carrier_member_id="106777777", mbi=None,
            row_class=RowClass.ENROLLMENT, amount=0.0, effective_date=date(2026, 1, 1),
        )
        r = resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                             source="commission_import")

        assert r.created_customer is False
        assert r.customer is None
        assert r.match_path == "parked"
        assert "match_suggestion" in r.actions
        assert Customer.query.count() == before    # no stub created

        ms = MatchSuggestion.query.filter_by(agency_id=agency.id, status="pending").first()
        assert ms is not None
        assert ms.stub_customer_id is None
        assert ms.suggested_customer_id is None
        assert ms.confidence == "parked"


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


def test_two_facts_same_mbi_one_transaction_no_autoflush_collision(db_session, app, agency, agent_user):
    """A member appears in MULTIPLE rows of one UHC file (renewal + chargeback +
    override). Resolving the 2nd fact must MATCH the SAME existing customer the
    1st fact attached to, in the SAME uncommitted transaction, without an
    autoflush collision on ix_customers_mbi.

    NOTE: this used to test the commission path CREATING a stub on f1 then
    re-finding it via crosswalk on f2 (the real UHC re-upload crash, the
    'Sweatt→AJ' incident). Under Task 1's ID-only match-or-park rule, the
    commission path never creates a customer, so that specific stub-creation
    autoflush race is now structurally impossible here — there's nothing to
    autoflush. The no-autoflush guarantee on the MBI matcher itself
    (_match_by_mbi's `with db.session.no_autoflush`) still matters whenever a
    customer already exists, so this test now seeds the customer up front and
    proves two same-MBI facts in one transaction both attach to it cleanly."""
    from app.extensions import db
    from app.models import Customer, Policy
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer

    with app.app_context():
        c = Customer(agency_id=agency.id, first_name="Ricky", last_name="Sweatt",
                     full_name="Ricky Sweatt", mbi="8NP5GM6TK40",
                     primary_agent_id=agent_user.id, source="bob")
        db.session.add(c); db.session.flush()

        f1 = MemberFact(carrier="UHC", full_name="SWEATT, RICKY L.", mbi="8NP5GM6TK40",
                        carrier_member_id=None, row_class=RowClass.RENEWAL, amount=28.92,
                        effective_date=date(2026, 1, 1))
        f2 = MemberFact(carrier="UHC", full_name="SWEATT, RICKY L.", mbi="8NP5GM6TK40",
                        carrier_member_id=None, row_class=RowClass.CHARGEBACK, amount=-268.0,
                        effective_date=date(2026, 1, 1))
        r1 = resolve_customer(f1, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        # NO commit between — same transaction, mirrors the ingest loop.
        r2 = resolve_customer(f2, agency_id=agency.id, agent_id=agent_user.id,
                              source="commission_import")
        db.session.commit()  # MUST NOT raise UniqueViolation on ix_customers_mbi

        assert r1.match_path == "mbi"
        assert r2.match_path in ("mbi", "crosswalk")
        assert r2.customer.id == r1.customer.id == c.id
        assert Customer.query.filter_by(agency_id=agency.id, mbi="8NP5GM6TK40").count() == 1


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
    """Real Humana files have rows with neither PID nor MBI nor DOB — i.e. NO
    unique carrier ID per the Task 1 ID-only rule. These now correctly PARK
    (enqueue a MatchSuggestion) instead of fabricating a phantom policy off a
    bare name. Verify each row gets its OWN suggestion (not collapsed/collided)
    and neither creates a customer or policy."""
    from app.extensions import db
    from app.models import Policy, Customer, MatchSuggestion
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
        r1 = resolve_customer(f1, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        r2 = resolve_customer(f2, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()  # must NOT raise IntegrityError

        assert r1.match_path == "parked"
        assert r2.match_path == "parked"
        assert Policy.query.filter_by(agency_id=agency.id, carrier="Humana").count() == 0
        assert Customer.query.filter_by(agency_id=agency.id).count() == 0
        assert MatchSuggestion.query.filter_by(agency_id=agency.id, status="pending").count() == 2


def test_humana_no_id_row_is_idempotent(db_session, app, agency, agent_user):
    """No-ID Humana row: each resolve PARKS (no policy/customer to dedupe
    against via crosswalk, since none is created) — verify re-upload doesn't
    crash and doesn't fabricate a policy."""
    from app.extensions import db
    from app.models import Policy, MatchSuggestion
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    with app.app_context():
        f = MemberFact(carrier="Humana", full_name="Helms Teressa", first_name="Teressa",
                       last_name="Helms", mbi=None, carrier_member_id=None,
                       row_class=RowClass.RENEWAL, amount=29.94,
                       source_ref="humana::CommissionData_1::226")
        r1 = resolve_customer(f, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()
        r2 = resolve_customer(f, agency_id=agency.id, agent_id=agent_user.id, source="commission_import")
        db.session.commit()
        assert r1.match_path == "parked"
        assert r2.match_path == "parked"
        assert Policy.query.filter_by(agency_id=agency.id, carrier="Humana").count() == 0


# ---------------------------------------------------------------------------
# Phase 1 — AOR timeline reconciliation (supersession by effective date)
# ---------------------------------------------------------------------------

def _seed_open_interval(db, agency, agent, customer, *, carrier, eff, plan="Old Plan"):
    from app.models import CustomerAorHistory
    from datetime import date
    aor = CustomerAorHistory(
        agency_id=agency.id, customer_id=customer.id, agent_id=agent.id,
        carrier=carrier, plan_name=plan, effective_date=eff, end_date=None,
        source="commission_import",
    )
    db.session.add(aor)
    db.session.flush()
    return aor


def test_later_enrollment_closes_earlier_open_interval(db_session, app, agency, agent_user):
    """The Tocara Brown case: an enrollment effective 6/1 supersedes an OPEN 3/1
    interval for the same (customer, carrier). The 3/1 interval is end-dated to
    the day before the new eff (5/31); exactly one interval stays open (6/1)."""
    from app.extensions import db
    from app.models import Customer, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="Humana", member_id="PIDTOCARA",
            mbi=None, first="Tocara", last="Brown",
        )
        # Existing open interval effective 3/1 (the one that should be superseded).
        _seed_open_interval(db, agency, agent_user, c, carrier="Humana",
                            eff=date(2026, 3, 1))
        db.session.commit()

        # New ENROLLMENT effective 6/1 arrives on the SAME policy (crosswalk path).
        fact = MemberFact(
            carrier="Humana", full_name="Brown Tocara", first_name="Tocara",
            last_name="Brown", carrier_member_id="PIDTOCARA",
            row_class=RowClass.ENROLLMENT, amount=202.42, effective_date=date(2026, 6, 1),
        )
        from app.commission.resolver import resolve_customer
        resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                         source="commission_import")
        db.session.commit()

        intervals = (CustomerAorHistory.query
                     .filter_by(customer_id=c.id, carrier="Humana")
                     .order_by(CustomerAorHistory.effective_date).all())
        assert len(intervals) == 2
        old, new = intervals
        assert old.effective_date == date(2026, 3, 1)
        assert old.end_date == date(2026, 5, 31)      # closed day-before new eff
        assert new.effective_date == date(2026, 6, 1)
        assert new.end_date is None                   # only the newest stays open


def test_renewal_does_not_open_or_supersede(db_session, app, agency, agent_user):
    """A RENEWAL row never opens a new interval and never supersedes — when an open
    interval already exists for the carrier, a renewal just confirms it."""
    from app.extensions import db
    from app.models import CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="Humana", member_id="PIDREN",
            first="Reuben", last="Walker",
        )
        _seed_open_interval(db, agency, agent_user, c, carrier="Humana",
                            eff=date(2026, 1, 1))
        db.session.commit()

        fact = MemberFact(
            carrier="Humana", full_name="Walker Reuben", first_name="Reuben",
            last_name="Walker", carrier_member_id="PIDREN",
            row_class=RowClass.RENEWAL, amount=28.92, effective_date=date(2026, 6, 1),
        )
        from app.commission.resolver import resolve_customer
        resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                         source="commission_import")
        db.session.commit()

        intervals = CustomerAorHistory.query.filter_by(
            customer_id=c.id, carrier="Humana").all()
        assert len(intervals) == 1                    # renewal opened nothing
        assert intervals[0].effective_date == date(2026, 1, 1)
        assert intervals[0].end_date is None          # left open / untouched


def test_first_interval_opens_for_bob_renewal_when_none_exists(db_session, app, agency, agent_user):
    """Bootstrap rule: when NO open interval exists for (customer, carrier), even a
    RENEWAL (how BOB rows arrive) opens the initial interval — never leave a customer
    with zero intervals."""
    from app.extensions import db
    from app.models import CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="UHC", member_id="UHCFIRST",
            mbi="MBIFIRST01", first="Faye", last="Irst",
        )
        db.session.commit()

        fact = MemberFact(
            carrier="UHC", full_name="Irst Faye", first_name="Faye", last_name="Irst",
            mbi="MBIFIRST01", carrier_member_id="UHCFIRST",
            row_class=RowClass.RENEWAL, amount=28.92, effective_date=date(2026, 1, 1),
        )
        from app.commission.resolver import resolve_customer
        resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id, source="bob")
        db.session.commit()

        intervals = CustomerAorHistory.query.filter_by(
            customer_id=c.id, carrier="UHC").all()
        assert len(intervals) == 1
        assert intervals[0].effective_date == date(2026, 1, 1)
        assert intervals[0].end_date is None


def test_supersession_uses_term_date_when_present(db_session, app, agency, agent_user):
    """When the incoming enrollment row carries a term_date for the prior coverage,
    the superseded interval is closed at that term_date (carrier-authoritative),
    not the derived new_eff-1."""
    from app.extensions import db
    from app.models import CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="Humana", member_id="PIDTERM",
            first="Terry", last="Mdate",
        )
        old = _seed_open_interval(db, agency, agent_user, c, carrier="Humana",
                                  eff=date(2026, 3, 1))
        db.session.commit()

        fact = MemberFact(
            carrier="Humana", full_name="Mdate Terry", first_name="Terry",
            last_name="Mdate", carrier_member_id="PIDTERM",
            row_class=RowClass.ENROLLMENT, amount=202.42,
            effective_date=date(2026, 6, 1), term_date=date(2026, 4, 30),
        )
        from app.commission.resolver import resolve_customer
        resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                         source="commission_import")
        db.session.commit()

        db.session.refresh(old)
        assert old.end_date == date(2026, 4, 30)      # used the row's term_date


def test_supersession_never_touches_later_or_already_closed_or_bcbs(db_session, app, agency, agent_user):
    """Guardrails: an incoming enrollment only closes OPEN, strictly-EARLIER intervals
    for the SAME carrier. It must not (a) close an already-closed interval, (b) close a
    later-effective open interval, or (c) close a BCBS interval (BCBS end_date is special)."""
    from app.extensions import db
    from app.models import CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass

    with app.app_context():
        c, p = _seed_customer_with_policy(
            db, agency, agent_user, carrier="Humana", member_id="PIDGUARD",
            first="Gloria", last="Uard",
        )
        # (a) already-closed earlier interval — must stay as-is
        closed = _seed_open_interval(db, agency, agent_user, c, carrier="Humana",
                                     eff=date(2025, 1, 1))
        closed.end_date = date(2025, 12, 31)
        # (b) a LATER open interval (eff 8/1) — must NOT be closed by a 6/1 enrollment
        later = _seed_open_interval(db, agency, agent_user, c, carrier="Humana",
                                    eff=date(2026, 8, 1))
        # (c) a BCBS open interval — different carrier, must be untouched
        bcbs = _seed_open_interval(db, agency, agent_user, c, carrier="BCBS",
                                   eff=date(2026, 2, 1))
        db.session.commit()

        fact = MemberFact(
            carrier="Humana", full_name="Uard Gloria", first_name="Gloria",
            last_name="Uard", carrier_member_id="PIDGUARD",
            row_class=RowClass.ENROLLMENT, amount=202.42, effective_date=date(2026, 6, 1),
        )
        from app.commission.resolver import resolve_customer
        resolve_customer(fact, agency_id=agency.id, agent_id=agent_user.id,
                         source="commission_import")
        db.session.commit()

        db.session.refresh(closed); db.session.refresh(later); db.session.refresh(bcbs)
        assert closed.end_date == date(2025, 12, 31)  # untouched (already closed)
        assert later.end_date is None                 # untouched (later eff)
        assert bcbs.end_date is None                  # untouched (other carrier)


def test_backfill_reconciles_existing_duplicate_open_intervals(db_session, app, agency, agent_user):
    """The backfill reproduces the supersession rule on legacy data: a customer with
    THREE open Humana intervals (3/1, 5/1, 6/1) is reconciled to a contiguous timeline
    — 3/1->4/30, 5/1->5/31, 6/1 open — closing each at the NEXT interval's eff-1. A
    lone open interval and a BCBS group are left untouched."""
    from app.extensions import db
    from app.models import CustomerAorHistory
    from scripts.backfill_reconcile_aor_intervals import reconcile_open_intervals

    with app.app_context():
        c, _ = _seed_customer_with_policy(
            db, agency, agent_user, carrier="Humana", member_id="PIDBF",
            first="Bertha", last="Fill",
        )
        i1 = _seed_open_interval(db, agency, agent_user, c, carrier="Humana", eff=date(2026, 3, 1))
        i2 = _seed_open_interval(db, agency, agent_user, c, carrier="Humana", eff=date(2026, 5, 1))
        i3 = _seed_open_interval(db, agency, agent_user, c, carrier="Humana", eff=date(2026, 6, 1))
        # A single open BCBS interval — must be ignored (BCBS excluded + only one).
        bcbs = _seed_open_interval(db, agency, agent_user, c, carrier="BCBS", eff=date(2026, 1, 1))
        db.session.commit()

        groups, closed = reconcile_open_intervals(verbose=False)
        db.session.commit()

        assert (groups, closed) == (1, 2)
        db.session.refresh(i1); db.session.refresh(i2); db.session.refresh(i3); db.session.refresh(bcbs)
        assert i1.end_date == date(2026, 4, 30)   # closed at next eff (5/1) - 1
        assert i2.end_date == date(2026, 5, 31)   # closed at next eff (6/1) - 1
        assert i3.end_date is None                # newest stays open
        assert bcbs.end_date is None              # untouched

        # Idempotent: a second pass finds nothing to close.
        groups2, closed2 = reconcile_open_intervals(verbose=False)
        assert (groups2, closed2) == (0, 0)


def test_unresolved_commission_row_with_no_agent_parks_never_attributes_to_uploader(db_session, app, agency):
    """A commission row that can't resolve to a real agent AND has no existing
    customer to attach to must PARK — under Task 1's ID-only match-or-park rule
    the commission path never creates a customer at all, which subsumes the
    older guarantee (never silently attribute an unresolved row to the
    uploading admin, the Sweatt→AJ bug): there's no customer for it to be
    mis-attributed to in the first place."""
    from app.extensions import db
    from app.models import Customer, CustomerAorHistory
    from app.commission.member_fact import MemberFact, RowClass
    from app.commission.resolver import resolve_customer
    from datetime import date

    with app.app_context():
        before = Customer.query.count()
        fact = MemberFact(
            carrier="UHC", full_name="SWEATT, RICKY L.", mbi="8NP5GM6TK40",
            row_class=RowClass.RENEWAL, amount=28.92, effective_date=date(2026, 1, 1),
        )
        # agent_id=None mirrors the upload path when no writing agent resolves.
        r = resolve_customer(fact, agency_id=agency.id, agent_id=None,
                             source="commission_import")
        db.session.commit()

        assert r.match_path == "parked"
        assert r.customer is None
        assert Customer.query.count() == before              # no stub, no misattribution
        # no fabricated AOR interval at all (parking opens none)
        assert CustomerAorHistory.query.count() == 0
