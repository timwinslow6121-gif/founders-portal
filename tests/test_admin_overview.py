"""Wiring guard for the admin_overview rewrite (Task 9): the route's agent
breakdown must reflect the FULL attributed book via app/metrics.book_breakdown,
not a re-derived/partial count. Uses the same db_session/app fixtures as
tests/test_metrics.py (create_app() takes no arg)."""
from app.extensions import db
from app.models import Agency, User, Policy
from app.metrics import Scope, book_breakdown


def test_agent_breakdown_counts_attributed_book(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        brian = User(name="Brian", email="b@x.com", agency_id=ag.id)
        db.session.add(brian); db.session.flush()
        for i in range(7):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=brian.id, agency_id=ag.id))
        db.session.commit()

        rows = book_breakdown(Scope(agency_id=ag.id))["by_agent"]
        brian_row = next(r for r in rows if r["agent_id"] == brian.id)
        assert brian_row["count"] == 7
