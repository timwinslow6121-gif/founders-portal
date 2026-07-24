"""Backfill full Humana MBIs onto customer records from Humana commission line
items. The Humana BOB masks the MBI (XXXXX + last 6), but commission statements
carry the FULL MBI on first-year/new rows. This puts the real MBI on the customer
(the domain model's 'customer owns the MBI'), helping every future reconcile,
dedup, and the switcher pass.

SAFETY:
  - Only fills a customer whose mbi is currently BLANK (never overwrites).
  - The value MUST pass the exact CMS MBI format (see is_valid_mbi) — a masked or
    malformed value is never written.
  - Refuses to write an MBI already held by a DIFFERENT customer (unique index).
Dry-run default; --apply commits.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_humana_mbi_from_commissions.py [--apply]
"""
import re
import sys
from app import create_app
from app.extensions import db
from app.models import CommissionLineItem, Customer

# CMS MBI: 11 chars, positions C A AN N A AN N A A N N; letters exclude S L O I B Z.
_L = "ACDEFGHJKMNPQRTUVWXY"
_MBI_RE = re.compile(
    r"^[1-9][%(L)s][0-9%(L)s][0-9][%(L)s][0-9%(L)s][0-9][%(L)s][%(L)s][0-9][0-9]$"
    % {"L": _L}
)


def is_valid_mbi(v):
    return bool(v) and bool(_MBI_RE.match(str(v).strip().upper()))


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — backfill full Humana MBIs from commissions\n" % ("APPLY" if apply else "DRY-RUN"))

        # customer_id -> a valid full MBI seen on a Humana commission line item
        cust_mbi = {}
        for x in CommissionLineItem.query.filter_by(carrier="Humana").all():
            if x.customer_id and is_valid_mbi(x.mbi):
                cust_mbi.setdefault(x.customer_id, str(x.mbi).strip().upper())

        filled = skipped_has = skipped_conflict = skipped_taken = invalid = 0
        for cid, mbi in cust_mbi.items():
            c = db.session.get(Customer, cid)
            if not c:
                continue
            if c.mbi:
                if c.mbi.strip().upper() == mbi:
                    skipped_has += 1
                else:
                    skipped_conflict += 1
                    print("  ! customer %s (%s) has DIFFERENT mbi %r != commission %s — SKIP"
                          % (cid, c.full_name, c.mbi, mbi))
                continue
            # would this MBI collide with another customer? (ix_customers_mbi)
            taken = (Customer.query
                     .filter(Customer.id != cid, Customer.mbi == mbi,
                             Customer.agency_id == c.agency_id).first())
            if taken:
                skipped_taken += 1
                print("  ! mbi %s already on customer %s (%s) — SKIP filling %s (%s)"
                      % (mbi, taken.id, taken.full_name, cid, c.full_name))
                continue
            print("  fill %-24s (cust %s) <- %s" % (c.full_name, cid, mbi))
            if apply:
                c.mbi = mbi
            filled += 1

        if apply:
            db.session.commit()
            print("\nAPPLIED — %d filled." % filled)
        else:
            db.session.rollback()
            print("\nDRY-RUN — would fill %d (already-match %d, conflict %d, mbi-taken %d)."
                  % (filled, skipped_has, skipped_conflict, skipped_taken))


if __name__ == "__main__":
    main("--apply" in sys.argv)
