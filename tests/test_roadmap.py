from datetime import date
import pytest


def test_roadmap_item_column_maps_status(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        cases = {
            "shipped": "shipped",
            "in_progress": "in_progress",
            "submitted": "planned",
            "acknowledged": "planned",
            "planned": "planned",
            "wont_fix": "hidden",
            "dismissed": "hidden",
        }
        for status, expected_col in cases.items():
            it = RoadmapItem(agency_id=agency.id, type="bug_fix",
                             title=f"t-{status}", status=status)
            db.session.add(it); db.session.flush()
            assert it.column == expected_col, f"{status} -> {it.column}, want {expected_col}"


def test_roadmap_item_known_issue_type_is_planned_column(db_session, app, agency):
    from app.extensions import db
    from app.models import RoadmapItem
    with app.app_context():
        it = RoadmapItem(agency_id=agency.id, type="known_issue",
                         title="counts mismatch", status="acknowledged")
        db.session.add(it); db.session.flush()
        assert it.column == "planned"
