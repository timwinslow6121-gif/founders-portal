from app.extensions import db
from app.models import Agency, Customer
from app.upload import _fill_if_blank


def test_pii_fill_blanks_does_not_overwrite(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        c = Customer(agency_id=ag.id, full_name="Jane Doe", first_name="Jane",
                     last_name="Doe", phone_primary="704-555-1111", dob=None)
        db.session.add(c); db.session.flush()
        _fill_if_blank(c, "phone_primary", "999-999-9999")   # existing → keep
        _fill_if_blank(c, "dob", __import__("datetime").date(1950, 1, 1))  # blank → fill
        assert c.phone_primary == "704-555-1111"
        assert c.dob is not None
