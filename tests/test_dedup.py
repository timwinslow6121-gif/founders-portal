import pytest
from datetime import date
from app.extensions import db
from app.models import Customer, Agency, Policy, CommissionLineItem, CommissionStatement
from app.dedup import find_no_mbi_clusters, cluster_signal


def _cust(agency_id, **kw):
    base = dict(agency_id=agency_id, first_name="", last_name="", stub=False)
    base.update(kw)
    c = Customer(**base)
    db.session.add(c)
    db.session.flush()
    return c


def test_connelly_blank_name_stubs_cluster_with_real_rows(app, db_session):
    with app.app_context():
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        agency_id = ag.id

        keeper = _cust(agency_id, first_name="John", last_name="Connelly",
                       full_name="John Connelly", mbi="4RH5X85DC65", dob=date(1953, 4, 7))
        _cust(agency_id, first_name="John", last_name="Connelly Iii",
              full_name="John Connelly Iii", dob=date(1953, 4, 7))
        _cust(agency_id, full_name="CONNELLY, JOHN", stub=True)            # blank first/last
        _cust(agency_id, full_name="CONNELLY, JOHN", dob=date(1953, 4, 7), stub=True)
        db.session.commit()

        clusters = find_no_mbi_clusters(agency_id)
        # All four Connelly rows form ONE cluster (full_name normalized + token-sorted).
        conn = [c for c in clusters if c.keeper_id == keeper.id]
        assert len(conn) == 1
        assert len(conn[0].member_ids) == 4
        # DOB shared by 3 of them => merge offered.
        assert conn[0].signal == "dob_match"


def test_contradictory_dob_is_conflict(app, db_session):
    with app.app_context():
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        agency_id = ag.id

        a = _cust(agency_id, first_name="Jane", last_name="Doe",
                  full_name="Jane Doe", dob=date(1950, 1, 1))
        _cust(agency_id, first_name="Jane", last_name="Doe",
              full_name="Jane Doe", dob=date(1962, 9, 9))
        db.session.commit()
        clusters = find_no_mbi_clusters(agency_id)
        doe = [c for c in clusters if a.id in c.member_ids][0]
        assert doe.signal == "conflict"


def test_bare_name_no_dob_no_id_is_name_only(app, db_session):
    with app.app_context():
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        agency_id = ag.id

        a = _cust(agency_id, first_name="Bob", last_name="Smith", full_name="Bob Smith")
        _cust(agency_id, first_name="Bob", last_name="Smith", full_name="Bob Smith", stub=True)
        db.session.commit()
        clusters = find_no_mbi_clusters(agency_id)
        smith = [c for c in clusters if a.id in c.member_ids][0]
        assert smith.signal == "name_only"


def test_shared_carrier_id_is_shared_id(app, db_session):
    with app.app_context():
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        agency_id = ag.id

        # Two same-name customers, both without DOB
        cust1 = _cust(agency_id, first_name="Alice", last_name="Brown", full_name="Alice Brown")
        cust2 = _cust(agency_id, first_name="Alice", last_name="Brown", full_name="Alice Brown")

        # Create a commission statement to use for the line items
        stmt = CommissionStatement(
            agency_id=agency_id,
            carrier="UHC",
            period_label="Jan 2026",
            statement_date=date(2026, 1, 31)
        )
        db.session.add(stmt)
        db.session.flush()

        # Attach commission line items with the same carrier_member_id to both customers
        # (This tests that _shared_carrier_ids detects a (carrier, carrier_member_id)
        # tuple spanning multiple customer rows)
        shared_member_id = "UHC12345"
        li1 = CommissionLineItem(
            agency_id=agency_id,
            statement_id=stmt.id,
            source_ref="uhc::1",
            carrier="UHC",
            carrier_member_id=shared_member_id,
            customer_id=cust1.id,
            member_name="Alice Brown",
            classification="agent_commission",
            raw_amount=100.0
        )
        li2 = CommissionLineItem(
            agency_id=agency_id,
            statement_id=stmt.id,
            source_ref="uhc::2",
            carrier="UHC",
            carrier_member_id=shared_member_id,
            customer_id=cust2.id,
            member_name="Alice Brown",
            classification="agent_commission",
            raw_amount=100.0
        )
        db.session.add(li1)
        db.session.add(li2)
        db.session.commit()

        clusters = find_no_mbi_clusters(agency_id)
        brown = [c for c in clusters if cust1.id in c.member_ids][0]
        assert brown.signal == "shared_id"


def test_one_person_many_product_lines_is_not_a_duplicate(app, db_session):
    """A person with a MAPD + a dental + a hospital-indemnity policy (no MBI on the
    latter two) is ONE customer with THREE policies — never flagged as duplicates."""
    with app.app_context():
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        agency_id = ag.id

        c = _cust(agency_id, first_name="Pat", last_name="Jones", full_name="Pat Jones",
                  mbi="9AB8X12CD34", dob=date(1955, 6, 1))
        for carrier, ptype, mid in [("UHC", "MAPD", "M1"),
                                    ("Aflac", "Hospital Indemnity", "H1"),
                                    ("VSP", "Dental Vision Hearing", "D1")]:
            db.session.add(Policy(agency_id=agency_id, carrier=carrier, member_id=mid,
                                  plan_type=ptype, customer_id=c.id, full_name="Pat Jones"))
        db.session.commit()
        clusters = find_no_mbi_clusters(agency_id)
        # Only one customer named Pat Jones — no cluster of size > 1.
        assert not any(c.id in cl.member_ids and len(cl.member_ids) > 1 for cl in clusters)
