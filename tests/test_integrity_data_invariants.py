from datetime import date
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, CommissionLineItem,
                        CommissionStatement, CustomerAorHistory, Plan)


def test_plan_id_orphans_counts_null_active_nonstub(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="Humana", member_id="M1",
                              status="active", plan_id=None))            # orphan
        pl = Plan(agency_id=a.id, carrier="Humana", cms_plan_id="H1-1", year=2026,
                  plan_name="X", plan_type="MAPD")
        db.session.add(pl); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="Humana", member_id="M2",
                              status="active", plan_id=pl.id))           # linked
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="uhc::0::5",
                              status="active", plan_id=None))            # stub, excluded
        db.session.commit()
        v = REGISTRY["plan_id_orphans"]()
        assert v.count == 1


def test_no_name_policies_counts_blank_names(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="N1",
                              status="active", first_name="", last_name=""))   # no name
        db.session.add(Policy(agency_id=a.id, carrier="UHC", member_id="N2",
                              status="active", first_name="Jane", last_name="Doe"))
        db.session.commit()
        assert REGISTRY["no_name_policies"]().count == 1


def test_payment_without_customer(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        st = CommissionStatement(agency_id=a.id, carrier="UHC", period_label="March 2026",
                                 statement_date=date(2026, 3, 1))
        db.session.add(st); db.session.flush()
        # money fact with NO customer link -> counts
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="UHC", source_ref="uhc::x::1", raw_amount=10.0,
            classification="agent_commission", customer_id=None))
        # money fact WITH a customer -> does not count
        c = Customer(agency_id=a.id, full_name="Has Cust", first_name="Has", last_name="Cust")
        db.session.add(c); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="UHC", source_ref="uhc::x::2", raw_amount=10.0,
            classification="agent_commission", customer_id=c.id))
        db.session.commit()
        assert REGISTRY["payment_without_customer"]().count == 1


def test_backwards_date_interval(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        u = User(name="A", email="a@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
        c = Customer(agency_id=a.id, full_name="X Y", first_name="X", last_name="Y", primary_agent_id=u.id)
        db.session.add(c); db.session.flush()
        db.session.add(CustomerAorHistory(agency_id=a.id, customer_id=c.id, agent_id=u.id,
            carrier="Aetna", effective_date=date(2026,1,1), end_date=date(2025,12,31)))  # backwards
        db.session.add(CustomerAorHistory(agency_id=a.id, customer_id=c.id, agent_id=u.id,
            carrier="UHC", effective_date=date(2024,1,1), end_date=date(2025,1,1)))      # fine
        db.session.commit()
        assert REGISTRY["backwards_date_interval"]().count == 1


def test_duplicate_customers_groups_by_name_dob_not_multi_aor(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        u = User(name="Ag", email="ag@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
        # John Connelly x3 (same person, same dob) -> 2 excess
        for fn in ["CONNELLY, JOHN", "John Connelly", "John Connelly Iii"]:
            db.session.add(Customer(agency_id=a.id, full_name=fn, first_name="John", last_name="Connelly",
                                    dob=date(1953,4,7), primary_agent_id=u.id))
        # A multi-AOR person: ONE customer with two policies/AORs -> must NOT be a dup
        m = Customer(agency_id=a.id, full_name="Multi Aor", first_name="Multi", last_name="Aor",
                     dob=date(1950,1,1), primary_agent_id=u.id)
        db.session.add(m); db.session.commit()
        v = REGISTRY["duplicate_customers"]()
        assert v.count == 2          # the 2 excess Connelly rows; Multi Aor not counted


def test_duplicate_customers_excludes_stubs(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        # Two stub customers with the SAME full_name and dob=None (pre-enrichment state)
        # These should NOT be clustered as a duplicate pair since stubs are excluded
        db.session.add(Customer(agency_id=a.id, full_name="Mystery Person", first_name="Mystery",
                                last_name="Person", dob=None, stub=True, source="commission_import"))
        db.session.add(Customer(agency_id=a.id, full_name="Mystery Person", first_name="Mystery",
                                last_name="Person", dob=None, stub=True, source="commission_import"))
        db.session.commit()
        v = REGISTRY["duplicate_customers"]()
        assert v.count == 0  # stubs are excluded; no duplicates detected


def test_orphan_stub_customers_exempts_manual_lead(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        # a garbage stub from import (counts)
        db.session.add(Customer(agency_id=a.id, full_name="STUB ONE", first_name="STUB", last_name="ONE",
                                stub=True, source="commission_import"))
        # a manual lead with no MBI (does NOT count — legitimate)
        db.session.add(Customer(agency_id=a.id, full_name="Real Lead", first_name="Real", last_name="Lead",
                                stub=False, source="manual", deal_stage="Lead", mbi=None))
        db.session.commit()
        v = REGISTRY["orphan_stub_customers"]()
        assert v.count == 1          # only the import stub


def test_duplicate_customers_ignores_null_dob_names(app, db_session):
    """Two non-stub customers with the SAME name but BOTH dob=None should NOT be
    clustered as a duplicate. Name alone (without DOB) is not identity."""
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        u = User(name="Ag", email="ag@x.com", agency_id=a.id); db.session.add(u); db.session.flush()
        # Two different real people who share a name, both with missing DOB
        db.session.add(Customer(agency_id=a.id, full_name="Jane Smith", first_name="Jane", last_name="Smith",
                                dob=None, stub=False, primary_agent_id=u.id))
        db.session.add(Customer(agency_id=a.id, full_name="Jane Smith", first_name="Jane", last_name="Smith",
                                dob=None, stub=False, primary_agent_id=u.id))
        # Also verify the positive case: same name + same real DOB STILL counts as duplicate
        db.session.add(Customer(agency_id=a.id, full_name="John Doe", first_name="John", last_name="Doe",
                                dob=date(1960,5,15), stub=False, primary_agent_id=u.id))
        db.session.add(Customer(agency_id=a.id, full_name="John Doe", first_name="John", last_name="Doe",
                                dob=date(1960,5,15), stub=False, primary_agent_id=u.id))
        db.session.commit()
        v = REGISTRY["duplicate_customers"]()
        # Only the two John Doe rows (same name+real dob) count as 1 excess;
        # the two Jane Smith rows (same name+NULL dob) do NOT count
        assert v.count == 1


def test_commission_import_stubs_invariant_counts_only_commission_stubs(app, db_session):
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        db.session.add(Customer(agency_id=a.id, first_name="A", last_name="B", full_name="A B",
                                stub=True, source="commission_import"))
        db.session.add(Customer(agency_id=a.id, first_name="C", last_name="D", full_name="C D",
                                stub=True, source="bob"))            # not counted
        db.session.commit()
        v = REGISTRY["commission_import_stubs"]()
        assert v.count == 1


def test_statement_balance_complete_is_ledger_internal_balance(app, db_session):
    """The invariant proves the LEDGER's internal balance per statement:
    Sigma(raw_amount) == Sigma(agent_payout) + Sigma(founders_keep) (via split_breakdown),
    which holds by construction. It is NOT line-items-vs-PolicyPayment — Founders-
    override / HRA rows the ledger records but PolicyPayment collapses must NOT flag
    (that's by design for Devoted/Healthspring)."""
    from app.integrity import REGISTRY
    with app.app_context():
        a = Agency(name="T"); db.session.add(a); db.session.flush()
        st = CommissionStatement(agency_id=a.id, carrier="Healthspring",
                                 period_label="May 2026", statement_date=date(2026, 5, 1))
        db.session.add(st); db.session.flush()
        # An agent_commission line that splits, PLUS a founders_override line with NO
        # matching PolicyPayment — the OLD (wrong) invariant would have flagged this as
        # a "dropped payment"; the corrected internal-balance invariant must NOT, because
        # split_breakdown(raw) == payout + keep for every row by construction.
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="Healthspring", source_ref="hs::x::1", raw_amount=100.0,
            classification="agent_commission", split_rate=0.55, customer_id=None))
        db.session.add(CommissionLineItem(agency_id=a.id, statement_id=st.id,
            carrier="Healthspring", source_ref="hs::x::1::ovr", raw_amount=4.59,
            classification="founders_override", split_rate=None, customer_id=None))
        db.session.commit()
        v = REGISTRY["statement_balance_complete"]()
        # this statement is internally balanced (no PolicyPayment needed) -> NOT flagged
        assert all(s["id"] != st.id for s in v.sample)
