"""Seed 1-2 example Medicare Updates (idempotent on agency_id+title).
Run: FLASK_APP=wsgi.py PYTHONPATH=. ./venv/bin/python3 scripts/seed_carrier_updates.py [--apply]"""
import sys
from app import create_app
from app.extensions import db
from app.models import CarrierUpdate, Plan

SEEDS = [
    {"update_type": "network", "carrier": "Humana",
     "title": "Humana added Tryon Medical Partners for 2026",
     "body": "Tryon Medical is in-network on Humana's 2026 MA plans — worth mentioning to "
             "clients who see Tryon providers.", "plan_hint": None},
    {"update_type": "commission", "carrier": "Humana",
     "title": "Example: a top plan going non-commissionable",
     "body": "Placeholder example — edit or delete. Shows how a commission-change post links "
             "to the affected plan so you see how many members it hits.",
     "plan_hint": "Gold Plus"},
]


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        created = 0
        for s in SEEDS:
            if CarrierUpdate.query.filter_by(agency_id=aid, title=s["title"]).first():
                print(f"skip (exists): {s['title']}"); continue
            plan_id = None
            if s.get("plan_hint"):
                pl = Plan.query.filter(Plan.agency_id == aid,
                                       Plan.plan_name.ilike(f"%{s['plan_hint']}%")).first()
                plan_id = pl.id if pl else None
            print(f"{'CREATE' if apply else 'would create'}: [{s['update_type']}] {s['title']}"
                  f"{' (plan '+str(plan_id)+')' if plan_id else ''}")
            if apply:
                db.session.add(CarrierUpdate(
                    agency_id=aid, update_type=s["update_type"], carrier=s["carrier"],
                    title=s["title"], body=s["body"], plan_id=plan_id, is_active=True))
                created += 1
        if apply:
            db.session.commit()
        print(f"done. created={created} (apply={apply})")


if __name__ == "__main__":
    main("--apply" in sys.argv)
