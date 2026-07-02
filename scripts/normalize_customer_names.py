"""Normalize customer names to the agency's 'First MI. Last' standard.
Recovers first/last for blank-first stubs from full_name; fixes ALL-CAPS + comma shapes.
Skips manually_edited rows. Dry-run by default; --apply writes. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/normalize_customer_names.py [--apply]
"""
import re
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Agency
from app.names import normalize_person_name, _tc

# Matches a first_name that already has a folded middle initial, e.g. "Katherine D."
_MI_FOLDED_RE = re.compile(r'.+ [A-Z]\.$')


def _canonical(src):
    """Parse a name string to (first, last, full) with MI folded into first_name."""
    first, mi, last, full = normalize_person_name(src)
    if mi:
        first = f"{first} {mi}."
        full = f"{first} {last}".strip()
    return first, last, full


def _desired(c):
    """Return (first, last, full) the row SHOULD have, or None if it's already correct/skip.

    Idempotency rule for middle-initial rows:
    normalize_person_name only extracts a middle initial from comma-separated input.
    Once we fold the MI into first_name (e.g. "Katherine D."), a second parse of
    "Katherine D. Bryant" (no comma) misreads last as "D. Bryant".  We must NOT
    flag an already-normalized MI row as needing a change.

    Detection: if current first_name already matches the folded-MI pattern
    (ends with " <single-uppercase-letter>."), the row is already canonical — skip it
    unless some OTHER field (last_name, full_name) is also wrong.
    """
    first_now = (c.first_name or "").strip()
    last_now  = (c.last_name  or "").strip()
    full_now  = (c.full_name  or "").strip()

    # If first_name is already in MI-folded form ("First X."), we must NOT re-parse
    # first_name (the no-comma parser would mis-split the MI into last). But the LAST
    # name can still be dirty (e.g. ALL-CAPS "BRYANT"), so normalize it on its own —
    # never trust a stored last_name to already be clean just because first is folded.
    if _MI_FOLDED_RE.match(first_now) and last_now:
        # Title-case each word of the last name directly (a lone "BRYANT" token would
        # be misread as a FIRST name by normalize_person_name, so use the per-word
        # caser the parser itself uses for last names).
        clean_last = " ".join(_tc(w) for w in last_now.split())
        expected_full = f"{first_now} {clean_last}".strip()
        if (last_now, full_now) == (clean_last, expected_full):
            return None                     # everything consistent, no change
        return (first_now, clean_last, expected_full)

    # Best source: full_name if first is blank, else first+last.
    # Use (c.last_name or '') to avoid "John None" when last_name is NULL.
    if not first_now:
        # Stub row: recover first/last from full_name
        src = full_now
    else:
        # first/last already set: check whether full_name carries a middle initial
        # we can safely recover.  Parse full_name; if it normalises to the SAME
        # first + last (case-insensitive) AND yields a non-empty MI, use full_name
        # as the canonical source so _canonical() folds the MI into first_name.
        # If full_name parses to a DIFFERENT person, ignore it — stored parts win.
        pf, pmi, pl, _ = normalize_person_name(full_now)
        if (pmi
                and pf.lower() == _tc(first_now).lower()
                and pl.lower() == " ".join(_tc(w) for w in last_now.split()).lower()):
            # full_name confirms same person AND carries an MI — use it as source
            src = full_now
        else:
            # full_name is absent, stale, or a different person — trust stored parts
            src = f"{first_now} {last_now}".strip()

    first, last, full = _canonical(src)
    if not first and not last:
        return None                         # nothing parseable; leave it
    if (first, last, full) == (first_now, last_now, full_now):
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
