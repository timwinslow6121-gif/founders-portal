"""tests/test_deceased_suppression.py"""
import csv
import io
from datetime import date


def _setup(app, agency):
    from app.extensions import db
    from app.models import Customer, User
    with app.app_context():
        u = User(email="x@t.com", name="X", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.flush()
        db.session.add(Customer(agency_id=agency.id, first_name="Alive", last_name="One",
                                full_name="Alive One", mbi="1AA1AA1AA11"))
        db.session.add(Customer(agency_id=agency.id, first_name="Linda", last_name="Bost",
                                full_name="Linda Bost", mbi="6MV0WK0MP06",
                                deceased_date=date(2026, 4, 30)))
        db.session.commit()
        return u.id


def _rows(resp):
    body = resp.data.decode()
    return list(csv.DictReader(io.StringIO(body.split("\n", 1)[1])))


def test_export_has_a_deceased_column(client, app, agency, db_session):
    uid = _setup(app, agency)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    rows = _rows(client.get("/customers/export"))
    assert "Deceased" in rows[0]
    by_name = {r["Name"]: r for r in rows}
    assert by_name["Linda Bost"]["Deceased"] == "2026-04-30"
    assert by_name["Alive One"]["Deceased"] == ""


def test_the_provenance_line_counts_the_deceased(client, app, agency, db_session):
    """A file that leaves the building must say it contains people not to mail."""
    uid = _setup(app, agency)
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    first = client.get("/customers/export").data.decode().splitlines()[0]
    assert "1 deceased" in first


def test_no_deceased_note_when_none_are_deceased(client, app, agency, db_session):
    from app.extensions import db
    from app.models import Customer, User
    with app.app_context():
        u = User(email="y@t.com", name="Y", is_admin=True, agency_id=agency.id)
        db.session.add(u); db.session.flush()
        db.session.add(Customer(agency_id=agency.id, first_name="Alive", last_name="One",
                                full_name="Alive One", mbi="1AA1AA1AA11"))
        db.session.commit()
        uid = u.id
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    first = client.get("/customers/export").data.decode().splitlines()[0]
    assert "deceased" not in first.lower()
