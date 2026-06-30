import pytest
from datetime import date
from app.extensions import db
from app.models import Customer, Agency
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
