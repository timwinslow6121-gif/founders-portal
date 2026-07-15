"""Seed the two public-safe starter notices (idempotent on agency_id+title).
The AEP countdown is auto-computed, NOT seeded here.
Run: FLASK_APP=wsgi.py PYTHONPATH=. ./venv/bin/python3 scripts/seed_agency_notices.py [--apply]"""
import sys
from app import create_app
from app.extensions import db
from app.models import AgencyNotice

SEEDS = [
    {"notice_type": "alert", "priority": 5, "title": "Founders Portal maintenance",
     "body": "Founders Portal maintenance is performed periodically. The portal may be "
             "briefly unavailable during updates."},
    {"notice_type": "info", "priority": 1, "title": "Portal is in active development",
     "body": "The Founders Portal is in active development. Some features may not work exactly "
             "as expected — thanks for your patience. Spotted something off? Log it on the Roadmap board."},
]


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        created = 0
        for s in SEEDS:
            exists = AgencyNotice.query.filter_by(agency_id=aid, title=s["title"]).first()
            if exists:
                print(f"skip (exists): {s['title']}")
                continue
            print(f"{'CREATE' if apply else 'would create'}: [{s['notice_type']}] {s['title']}")
            if apply:
                db.session.add(AgencyNotice(agency_id=aid, is_active=True, **s))
                created += 1
        if apply:
            db.session.commit()
        print(f"done. created={created} (apply={apply})")


if __name__ == "__main__":
    main("--apply" in sys.argv)
