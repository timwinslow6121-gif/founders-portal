from datetime import date, timedelta

from app.extensions import db
from app.models import Agency, AgencyNotice


def _mk(agency_id, **kw):
    n = AgencyNotice(
        agency_id=agency_id,
        notice_type=kw.get("notice_type", "info"),
        title=kw.get("title", "T"),
        body=kw.get("body", "B"),
        is_active=kw.get("is_active", True),
        show_until=kw.get("show_until"),
        priority=kw.get("priority", 0),
    )
    db.session.add(n)
    db.session.commit()
    return n


def test_visible_for_filters_and_orders(db_session, app, agency):
    with app.app_context():
        other_agency = Agency(name="Other Agency")
        db.session.add(other_agency)
        db.session.commit()

        today = date(2026, 7, 14)
        active = _mk(agency.id, title="active", priority=5)
        _mk(agency.id, title="inactive", is_active=False)
        _mk(agency.id, title="expired", show_until=today - timedelta(days=1))
        future = _mk(agency.id, title="future_exp", show_until=today + timedelta(days=1), priority=1)
        _mk(other_agency.id, title="other_agency", priority=99)

        rows = AgencyNotice.visible_for(agency.id, today)
        titles = [r.title for r in rows]
        assert titles == ["active", "future_exp"]  # inactive/expired/other-agency excluded; priority desc
        assert active.id and future.id


from app.notices import next_aep, NOTICE_PRESENTATION


def test_next_aep_before_oct15():
    assert next_aep(date(2026, 7, 14)) == (93, 2026)

def test_next_aep_on_oct15():
    assert next_aep(date(2026, 10, 15)) == (0, 2026)

def test_next_aep_after_oct15_rolls_to_next_year():
    d, y = next_aep(date(2026, 11, 1))
    assert y == 2027
    assert d == (date(2027, 10, 15) - date(2026, 11, 1)).days

def test_notice_presentation_covers_types():
    assert set(NOTICE_PRESENTATION) == {"info", "alert"}
    for v in NOTICE_PRESENTATION.values():
        assert "accent" in v and "icon" in v
