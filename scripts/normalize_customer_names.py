"""Normalize customer names to the agency's 'First MI. Last' standard.
Recovers first/last for blank-first stubs from full_name; fixes ALL-CAPS + comma shapes.
Skips manually_edited rows. Dry-run by default; --apply writes. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/normalize_customer_names.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from app.names import normalize_person_name


def _desired(c):
    """Return (first, last, full) the row SHOULD have, or None if it's already correct."""
    # Best source: full_name if first is blank, else first+last.
    src = (c.full_name or "").strip() if not (c.first_name or "").strip() \
        else f"{c.first_name} {c.last_name}".strip()
    first, mi, last, full = normalize_person_name(src)
    if mi:
        first = f"{first} {mi}."           # MI rides inside first_name
        full = f"{first} {last}".strip()
    if not first and not last:
        return None                         # nothing parseable; leave it
    if (first, last, full) == (c.first_name, c.last_name, c.full_name):
        return None                         # already clean
    return (first, last, full)


def plan_name_changes(agency_id):
    out = []
    q = (Customer.query
         .filter(Customer.agency_id == agency_id, Customer.manually_edited.is_(False)))
    for c in q.all():
        d = _desired(c)
        if d:
            out.append({"id": c.id, "old": c.full_name,
                        "new_first": d[0], "new_last": d[1], "new_full": d[2]})
    return out


def main(apply=False):
    app = create_app()
    with app.app_context():
        total = 0
        for ag in Agency.query.all():
            changes = plan_name_changes(ag.id)
            print(f"agency {ag.id}: {len(changes)} names to normalize")
            for ch in changes:
                print(f"  {ch['id']}: {ch['old']!r} -> {ch['new_full']!r}")
                if apply:
                    c = db.session.get(Customer, ch["id"])
                    c.first_name, c.last_name, c.full_name = \
                        ch["new_first"], ch["new_last"], ch["new_full"]
                    total += 1
            if apply:
                db.session.commit()
        print(f"\n{'APPLIED ' + str(total) + ' changes.' if apply else 'DRY-RUN — nothing written. Re-run with --apply.'}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
