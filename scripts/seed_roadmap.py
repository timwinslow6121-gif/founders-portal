"""Seed the Roadmap & Changelog with curated highlights from the real shipped
history (plain agent-friendly language). Idempotent on (agency_id, title).
Dry-run default; --apply commits. Tim reviews/edits the wording in the admin UI
after seeding.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_roadmap.py [--apply] [--agency N]
"""
import sys
from datetime import date

from app import create_app
from app.extensions import db
from app.models import RoadmapItem, Agency


SEED = [
    # type, status, title, issue_text, fix_text, priority, shipped_on
    dict(type="bug_fix", status="shipped", priority="high", shipped_on=date(2026, 6, 29),
         title="UHC HRA payments going to the wrong agent",
         issue_text="An HRA payment could be attributed to the wrong agent at the wrong rate (e.g. to Rebekah at 55% instead of the agent who actually wrote it).",
         fix_text="We now read the real writing agent from the payment detail and split at their correct contract rate."),
    dict(type="bug_fix", status="shipped", priority="high", shipped_on=date(2026, 6, 29),
         title="Commission Fidelity page was slow / unresponsive",
         issue_text="The UHC Fidelity view (~4,000 lines) loaded slowly and timed out; the agent filter reset every time you saved an edit.",
         fix_text="Rebuilt it to load light and save edits instantly in place — no reload, and your filter now stays put."),
    dict(type="bug_fix", status="shipped", priority="medium", shipped_on=date(2026, 6, 29),
         title="UHC Part D $4.59 payments weren't splitting to the agent",
         issue_text="A $4.59 Part D renewal was being kept 100% by Founders instead of split with the agent.",
         fix_text="Part D $4.59 renewals now split at the agent's contract rate; the other plan types are unchanged."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 26),
         title="Commission import no longer creates duplicate customers",
         issue_text="Uploading a commission statement could spawn duplicate customer records.",
         fix_text="Commission import now matches a payment to an existing customer by their carrier ID, or parks it for review — it never invents a customer. The book of business is the only place customers are created."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 26),
         title="Data-integrity radar",
         issue_text="It was hard to know if a fix in one place quietly broke something elsewhere.",
         fix_text="A behind-the-scenes system continuously checks the portal's data for problems, so we catch issues before they reach you."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 9),
         title="Agent commission recap",
         fix_text="A single-screen recap of your commissions by carrier, with every line tracing back to the file."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 9),
         title="Fresh Founders look (blue & green theme)",
         fix_text="The portal was re-themed to the Founders brand — cleaner, with light and dark modes."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 10),
         title="Security hardening + nightly off-site backups",
         fix_text="Added session security, an audit log, breach alerting, and encrypted nightly backups so your data is safe."),
    dict(type="feature", status="shipped", shipped_on=date(2026, 6, 23),
         title="All six commission carriers reconcile to the penny",
         fix_text="UHC, Humana, Aetna, BCBS, Devoted and Healthspring commission files now all balance exactly."),
    # planned / known
    dict(type="planned", status="planned", priority="medium",
         title="Merge duplicate customer records",
         issue_text="Some customers show up more than once (e.g. one person split across several rows).",
         fix_text=None),
    dict(type="known_issue", status="acknowledged", priority="low",
         title="Some plan pages show different member counts",
         issue_text="A plan's page and the carrier breakdown can show different counts because they're computed off different keys. We know about it — the fix is underway.",
         fix_text=None),
    dict(type="feature", status="in_progress", priority="high",
         title="This Roadmap & Changelog page",
         issue_text=None,
         fix_text="A live record of what we've fixed and what's planned — plus a way for you to report issues you find."),
]


def seed_items(agency_id, apply=False):
    """Upsert the SEED list for one agency, idempotent on (agency_id, title).
    Returns the number of NEW rows inserted."""
    inserted = 0
    for s in SEED:
        exists = RoadmapItem.query.filter_by(agency_id=agency_id, title=s["title"]).first()
        if exists:
            continue
        db.session.add(RoadmapItem(
            agency_id=agency_id, type=s["type"], status=s["status"], title=s["title"],
            issue_text=s.get("issue_text"), fix_text=s.get("fix_text"),
            priority=s.get("priority"), shipped_on=s.get("shipped_on")))
        inserted += 1
        print(f"  + {s['status']:11} {s['title']}")
    if apply:
        db.session.commit()
        print(f"\nAPPLIED — {inserted} new roadmap items committed.")
    else:
        db.session.rollback()
        print(f"\nDRY-RUN — would insert {inserted}. Re-run with --apply to commit.")
    return inserted


def main(apply, agency_id):
    app = create_app()
    with app.app_context():
        if agency_id is None:
            agency = Agency.query.order_by(Agency.id).first()
            agency_id = agency.id
        seed_items(agency_id, apply=apply)


if __name__ == "__main__":
    aid = None
    if "--agency" in sys.argv:
        aid = int(sys.argv[sys.argv.index("--agency") + 1])
    main("--apply" in sys.argv, aid)
