"""tests/test_carrier_provenance_writer.py"""
from datetime import date


def _cust(app, agency, **kw):
    from app.extensions import db
    from app.models import Customer
    c = Customer(agency_id=agency.id, first_name="A", last_name="B",
                 full_name="A B", **kw)
    db.session.add(c); db.session.commit()
    return c


def test_carrier_value_writes_when_the_field_is_empty(app, agency, db_session):
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        assert set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        assert c.deceased_date == date(2026, 4, 30)


def test_a_carrier_never_clears_an_existing_deceased_date(app, agency, db_session):
    """Never-erase: a later file that no longer mentions the death must not undo it."""
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency, deceased_date=date(2026, 4, 30))
        assert set_carrier_value(c, "deceased_date", None, "uhc_commission") is False
        assert c.deceased_date == date(2026, 4, 30)


def test_a_carrier_cannot_overwrite_an_agents_mark(app, agency, db_session):
    """agent_entered outranks carrier_import."""
    from app.customer_provenance import set_carrier_value, set_human_value
    from app.models import User
    with app.app_context():
        u = User(email="a@t.com", name="Agent A", agency_id=agency.id)
        db_session.add(u); db_session.commit()
        c = _cust(app, agency)
        set_human_value(c, "deceased_date", date(2026, 1, 1), u)
        assert set_carrier_value(c, "deceased_date", date(2026, 8, 8), "humana_bob") is False
        assert c.deceased_date == date(2026, 1, 1)


def test_a_carrier_may_correct_its_own_earlier_value(app, agency, db_session):
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        assert set_carrier_value(c, "deceased_date", date(2026, 4, 15), "uhc_commission")
        assert c.deceased_date == date(2026, 4, 15)


def test_it_records_who_and_when(app, agency, db_session):
    import json
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        set_carrier_value(c, "deceased_date", date(2026, 4, 30), "uhc_commission")
        meta = json.loads(c.field_provenance)["_meta"]["deceased_date"]
        assert meta["source"] == "uhc_commission"
        assert meta["trust"] == "carrier_import"
        assert meta["value"] == "2026-04-30"


def test_an_unknown_field_is_rejected(app, agency, db_session):
    import pytest
    from app.customer_provenance import set_carrier_value
    with app.app_context():
        c = _cust(app, agency)
        with pytest.raises(ValueError):
            set_carrier_value(c, "not_a_field", "x", "uhc_commission")
