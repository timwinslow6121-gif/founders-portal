"""Bring the Roadmap & Changelog current with July 2026 shipped work + fix the 3
stale statuses left over from the 2026-06-30 seed. Idempotent on (agency_id,
title): re-running never duplicates. Dry-run default; --apply commits. Tim
reviews/edits the wording in the admin UI after seeding.

Two operations:
  1. INSERT the new July items (skip any whose title already exists).
  2. UPDATE the status/fix_text of 3 items seeded 06-30 that have since moved on
     (only touches them if they still hold the OLD status — idempotent).

Run on VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_roadmap_july.py [--apply] [--agency N]
"""
import sys
from datetime import date

from app import create_app
from app.extensions import db
from app.models import RoadmapItem, Agency


# --- 1. New items to add (agent-facing plain language) ----------------------
SEED = [
    dict(type="feature", status="shipped", priority="high", shipped_on=date(2026, 7, 14),
         title="New login page + Agency Notice Board",
         issue_text="The old login logo didn't fit the brand, and there was no shared place for agency-wide notices before you sign in.",
         fix_text="A clean Founders split-screen login with an Agency Notice Board — an automatic AEP countdown plus admin-posted notices — visible before you log in."),
    dict(type="feature", status="shipped", priority="high", shipped_on=date(2026, 7, 15),
         title="Medicare Updates Hub",
         issue_text="There was no single place to stay current on the carrier changes that move commissions and sales (a plan going non-commissionable, a network change, important dates).",
         fix_text="A shared behind-login board where any agent can post typed, carrier-tagged updates — optionally linked to a plan so it shows 'Affects [plan] · N active members'."),
    dict(type="feature", status="shipped", priority="medium", shipped_on=date(2026, 7, 13),
         title="Plan pages redesigned",
         issue_text="Plan detail pages showed every possible field, including ones that didn't apply to the plan type — cluttered and hard to read.",
         fix_text="Each plan page is now a condensed benefits snapshot that shows only what's relevant to that plan type (Part C, PDP, Medigap, DVH, Hospital Indemnity), with member count as the headline."),
    dict(type="feature", status="shipped", priority="medium", shipped_on=date(2026, 7, 13),
         title="Carriers & Plans page redesigned + made accurate",
         issue_text="The carriers page was a cluttered table, and some plan member counts and plan types were wrong.",
         fix_text="A cleaner page with coverage chips, search, and filters (network / SNP / drug) — plus corrected plan-type data (MAPD vs MA-only) from the authoritative NC Landscape."),
    dict(type="feature", status="shipped", priority="low", shipped_on=date(2026, 7, 13),
         title="Preferred-language tag on customers",
         issue_text="There was no way to record and filter customers by preferred language (e.g. Spanish-only).",
         fix_text="A Language field on the customer profile, editable inline, with a Language filter on the customers list."),
    dict(type="bug_fix", status="shipped", priority="high", shipped_on=date(2026, 7, 13),
         title="Fixed wrong plan member counts",
         issue_text="A plan's page could show the wrong number of members — Gold Plus showed 500 when it really had 1,803, and some plans showed 0.",
         fix_text="Plan pages now count members the same way the carrier breakdown does, so the numbers match everywhere (verified across all plans)."),
    dict(type="feature", status="shipped", priority="high", shipped_on=date(2026, 7, 18),
         title="Merge customers even without a shared ID",
         issue_text="The same person imported from different carriers could show up as several records that couldn't be merged because they didn't share an MBI.",
         fix_text="You can now merge duplicate customer records that were split across carriers, collapsing them into one clean profile."),
    dict(type="bug_fix", status="shipped", priority="medium", shipped_on=date(2026, 7, 18),
         title="Cleaner duplicate-customer suggestions",
         issue_text="The duplicates page suggested far too many merges — including people who just happened to share a name but had different birthdates.",
         fix_text="Duplicate suggestions now treat same-name-but-different-birthdate as different people, cutting the noise dramatically so the real duplicates stand out."),
    dict(type="bug_fix", status="shipped", priority="medium", shipped_on=date(2026, 7, 18),
         title="Fixed the customer-merge engine",
         issue_text="Some duplicate merges failed with a database error and couldn't be completed.",
         fix_text="Fixed the underlying merge logic so previously-stuck duplicate merges now go through cleanly, with no money or policies lost."),
    dict(type="feature", status="shipped", priority="high", shipped_on=date(2026, 7, 15),
         title="Carrier book reconciliation — matched to the penny",
         issue_text="A carrier's book of business and the portal's records didn't always agree on who's active.",
         fix_text="We reconciled UHC's book line-by-line against the portal (with the money verified intact) and cleaned up phantom/duplicate records — the same careful method we're rolling out carrier by carrier."),

    # In-progress (reconciliation is ongoing across carriers)
    dict(type="feature", status="in_progress", priority="high",
         title="Making every carrier's book match to the penny",
         issue_text="Across carriers, the portal's active customers/policies should exactly match each carrier's official book of business.",
         fix_text="An ongoing carrier-by-carrier reconciliation — UHC, Aetna and HealthSpring are done; the rest continue as we receive each carrier's full book."),
]


# --- 2. Status corrections for items seeded 06-30 that have since moved on ----
# (title, expected_old_status, new_status, optional new fix_text)
UPDATES = [
    ("This Roadmap & Changelog page", "in_progress", "shipped",
     "A live record of what we've fixed and what's planned — plus a way for you to report issues you find.",
     date(2026, 6, 30)),
    ("Some plan pages show different member counts", "acknowledged", "shipped",
     "Fixed — plan pages and the carrier breakdown now count members the same way, so they agree everywhere.",
     date(2026, 7, 13)),
    ("Merge duplicate customer records", "planned", "shipped",
     "You can now merge duplicate customer records — including ones split across carriers with no shared ID.",
     date(2026, 7, 18)),
]


def run(agency_id, apply=False):
    inserted = 0
    updated = 0

    for s in SEED:
        if RoadmapItem.query.filter_by(agency_id=agency_id, title=s["title"]).first():
            continue
        db.session.add(RoadmapItem(
            agency_id=agency_id, type=s["type"], status=s["status"], title=s["title"],
            issue_text=s.get("issue_text"), fix_text=s.get("fix_text"),
            priority=s.get("priority"), shipped_on=s.get("shipped_on")))
        inserted += 1
        print(f"  + {s['status']:11} {s['title']}")

    for title, old_status, new_status, fix_text, shipped_on in UPDATES:
        it = RoadmapItem.query.filter_by(agency_id=agency_id, title=title).first()
        if it is None:
            print(f"  ? UPDATE target not found (skipped): {title}")
            continue
        if it.status == old_status:               # idempotent: only move it once
            it.status = new_status
            it.fix_text = fix_text
            it.shipped_on = shipped_on
            updated += 1
            print(f"  ~ {old_status} -> {new_status:11} {title}")
        else:
            print(f"  = already {it.status} (no change): {title}")

    if apply:
        db.session.commit()
        print(f"\nAPPLIED — {inserted} new, {updated} status-updated.")
    else:
        db.session.rollback()
        print(f"\nDRY-RUN — would insert {inserted}, update {updated}. Re-run with --apply.")
    return inserted, updated


def main(apply, agency_id):
    app = create_app()
    with app.app_context():
        if agency_id is None:
            agency_id = Agency.query.order_by(Agency.id).first().id
        run(agency_id, apply=apply)


if __name__ == "__main__":
    aid = None
    if "--agency" in sys.argv:
        aid = int(sys.argv[sys.argv.index("--agency") + 1])
    main("--apply" in sys.argv, aid)
