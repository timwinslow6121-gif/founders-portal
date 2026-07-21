import pytest
from datetime import date
from app.extensions import db
from app.models import Customer, Agency, Policy, CommissionLineItem, CommissionStatement
from app.models import CustomerAorHistory, User
from app.dedup import find_no_mbi_clusters, cluster_signal, is_reissued_mbi_candidate
from app.customers import merge_customers


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


def test_contradictory_dob_does_not_cluster(app, db_session):
    """Same name + two DIFFERENT present DOBs = two different people → NOT a merge
    suggestion at all (DOB-aware splitting, 2026-07-18; BOB dobs are credible).
    Previously these clustered with signal='conflict'; now they don't surface.
    A genuine conflict (same dob, different mbi) still clusters — covered elsewhere."""
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
        assert not any(a.id in c.member_ids for c in clusters)


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


def test_merge_adopts_loser_mbi_three_way(app, db_session):
    """A keeper with no MBI + a loser carrying one → keeper adopts it, loser gone,
    no IntegrityError. 3-way shape (keeper + two losers, one carries the MBI)."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        keeper = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", dob=date(1951, 5, 6))   # no mbi
        loser1 = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", dob=date(1951, 5, 6),
                       mbi="7WY1YQ0NP99", stub=True)                       # carries mbi
        loser2 = _cust(aid, first_name="Annie", last_name="Maready",
                       full_name="Annie Maready", stub=True)              # no mbi/dob
        db.session.commit()
        res = merge_customers(keeper.id, [loser1.id, loser2.id], aid, "test")
        db.session.commit()
        assert res["ok"] is True and res["merged"] == 2
        k = db.session.get(Customer, keeper.id)
        assert k is not None and k.mbi == "7WY1YQ0NP99"
        assert db.session.get(Customer, loser1.id) is None
        assert db.session.get(Customer, loser2.id) is None


def test_merge_shared_aor_chapter_no_null_customer(app, db_session):
    """Keeper + loser each hold the SAME (carrier, effective_date) AOR chapter →
    after merge the keeper has exactly one, no AOR row has NULL customer_id, loser gone."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        keeper = _cust(aid, first_name="Jerry", last_name="Goodman",
                       full_name="Jerry Goodman", dob=date(1945, 5, 16))
        loser = _cust(aid, first_name="Jerry", last_name="Goodman",
                      full_name="Jerry Goodman", dob=date(1945, 5, 16), stub=True)
        agent = User(name="A", email="aor-agent@x.com", agency_id=aid)
        db.session.add(agent); db.session.flush()
        for cid in (keeper.id, loser.id):
            db.session.add(CustomerAorHistory(
                agency_id=aid, customer_id=cid, agent_id=agent.id, carrier="Humana",
                effective_date=date(2024, 1, 1)))
        db.session.commit()
        res = merge_customers(keeper.id, [loser.id], aid, "test")
        db.session.commit()
        assert res["ok"] is True
        chapters = CustomerAorHistory.query.filter_by(customer_id=keeper.id).all()
        assert len(chapters) == 1 and chapters[0].effective_date == date(2024, 1, 1)
        # no orphaned / null-customer AOR rows anywhere
        assert CustomerAorHistory.query.filter(
            CustomerAorHistory.customer_id.is_(None)).count() == 0
        assert db.session.get(Customer, loser.id) is None


def test_different_dob_same_name_does_not_cluster(app, db_session):
    """Two same-name people with DIFFERENT present DOBs are NOT a merge suggestion
    (George Miller: 1952-04-19/Justin vs 1921-06-28/Brian = two different people)."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        _cust(aid, first_name="George", last_name="Miller",
              full_name="George Miller", dob=date(1952, 4, 19))
        _cust(aid, first_name="George", last_name="Miller",
              full_name="George Miller", dob=date(1921, 6, 28))
        db.session.commit()
        clusters = find_no_mbi_clusters(aid)
        # no cluster: each distinct-dob George Miller is a lone row -> not a suggestion
        assert clusters == []


def test_same_dob_still_clusters(app, db_session):
    """Same name + same DOB still surfaces as a merge candidate."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        _cust(aid, first_name="Mary", last_name="Smith",
              full_name="Mary Smith", dob=date(1950, 1, 1))
        _cust(aid, first_name="Mary", last_name="Smith",
              full_name="Mary Smith", dob=date(1950, 1, 1), stub=True)
        db.session.commit()
        clusters = find_no_mbi_clusters(aid)
        assert len(clusters) == 1 and len(clusters[0].member_ids) == 2


def test_null_dob_joins_single_dob_group(app, db_session):
    """A no-DOB stub clusters with the real record when there's ONE distinct DOB."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        _cust(aid, first_name="Joe", last_name="Brown",
              full_name="Joe Brown", dob=date(1955, 3, 3))
        _cust(aid, first_name="Joe", last_name="Brown",
              full_name="Joe Brown", stub=True)  # no dob
        db.session.commit()
        clusters = find_no_mbi_clusters(aid)
        assert len(clusters) == 1 and len(clusters[0].member_ids) == 2


def test_mixed_cluster_splits_by_dob(app, db_session):
    """3 same-name rows: two share a DOB (merge), one has a different DOB (dropped),
    a null-DOB row with 2+ distinct DOBs present is ambiguous -> left out."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        _cust(aid, full_name="Al Green", first_name="Al", last_name="Green", dob=date(1960, 5, 5))
        _cust(aid, full_name="Al Green", first_name="Al", last_name="Green", dob=date(1960, 5, 5), stub=True)
        _cust(aid, full_name="Al Green", first_name="Al", last_name="Green", dob=date(1930, 8, 8))  # different person
        _cust(aid, full_name="Al Green", first_name="Al", last_name="Green", stub=True)  # null dob, ambiguous
        db.session.commit()
        clusters = find_no_mbi_clusters(aid)
        # exactly one cluster: the two 1960 rows. The 1930 lone row + the ambiguous null-dob row are NOT suggestions.
        assert len(clusters) == 1 and len(clusters[0].member_ids) == 2


def test_same_dob_different_mbi_still_conflict(app, db_session):
    """A genuine conflict (same name + SAME dob + different MBIs — e.g. coexistence
    like Jana Benson's Medigap+DVH, or a switcher) STILL clusters as 'conflict' so a
    human reviews it. DOB-aware splitting only drops DIFFERENT-dob rows."""
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        aid = ag.id
        a = _cust(aid, first_name="Jana", last_name="Benson", full_name="Jana Benson",
                  dob=date(1959, 8, 24), mbi="45039665600")
        _cust(aid, first_name="Jana", last_name="Benson", full_name="Jana Benson",
              dob=date(1959, 8, 24), mbi="3DJ9F94VV42")
        db.session.commit()
        clusters = find_no_mbi_clusters(aid)
        c = [cl for cl in clusters if a.id in cl.member_ids]
        assert len(c) == 1 and c[0].signal == "conflict"


def test_reissued_candidate_true_same_dob_diff_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, first_name="Milton", last_name="Frazier",
                  full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, first_name="Milton", last_name="Frazier",
                  full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is True


def test_reissued_candidate_false_diff_dob(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1961, 9, 9), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_null_dob(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=None, mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_null_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi=None)
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_same_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_three_records(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="AAA")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="BBB")
        c = _cust(ag.id, dob=date(1950, 2, 3), mbi="CCC")
        assert is_reissued_mbi_candidate([a, b, c]) is False
