"""Restore the middle initials lost in the 2026-08-27 BCBS stub merge.

merge_customers is fill-blanks-only, so when the BOB record (keeper, "Opal
Abernathy") absorbed the legacy stub (loser, "Opal S. Abernathy"), first_name
was NOT blank and the middle initial was discarded on 43 of 46 keepers.

Middle initials do real work in this book: 189 other customers carry one, and
the July name-normalization deliberately preserved 248 of them because they
disambiguate people who share a name (Beaver x3, Barringer x2). This merge
produced a bare "Betty Beaver" and "Colleen Beaver" in a book that also holds
"Bethany B. Beaver".

Names below were recovered from the pre-merge dump
/root/founders_pre_bcbs_merge_20260827_184317.sql (the loser rows' first_name).

SAFETY: only writes when the current first_name is the SAME name without the
initial (e.g. "Opal" -> "Opal S."). If a keeper has since been edited to
anything else, the row is SKIPPED and reported — never overwrite a human edit.
Also refreshes full_name to stay consistent with the Customer name event.

Dry-run by default; --apply to write.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/restore_bcbs_merge_middle_initials.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Customer

AGENCY_ID = 1

# keeper customer id -> the first_name (with middle initial) from the merged stub
NAMES = {
    14866: 'Opal S.',
    14867: 'Marilyn L.',
    14868: 'Nancy R.',
    14869: 'Shelby P.',
    14870: 'Mary B.',
    14871: 'Beatrice M.',
    14872: 'Rita C.',
    14873: 'Cindy M.',
    14874: 'Margaret P.',
    14875: 'Sherry J.',
    14876: 'Susan M.',
    14877: 'Martha M.',
    14878: 'Gail B.',
    14879: 'Yvonne T.',
    14880: 'Anita B.',
    14881: 'Donna B.',
    14882: 'Phil M.',
    14883: 'Carol K.',
    14884: 'Wilma K.',
    14885: 'Kay M.',
    14886: 'Kristie F.',
    14887: 'Sue R.',
    14888: 'Betty A.',
    14889: 'Cynthia B.',
    14890: 'Karen S.',
    14891: 'Deborah S.',
    14892: 'Lydia W.',
    14893: 'Vivian C.',
    14894: 'Ruth L.',
    14895: 'Linda H.',
    14896: 'Kathy J.',
    14897: 'Michael R.',
    14898: 'Tammy S.',
    14899: 'Wanda H.',
    14900: 'Ann M.',
    14901: 'Norma L.',
    14902: 'Sandra C.',
    14903: 'Edward A.',
    14904: 'Colleen E.',
    14905: 'Dee A.',
    14907: 'Sylvia S.',
    14909: 'Paula R.',
    14910: 'Rita A.',
}


def main(apply):
    app = create_app()
    with app.app_context():
        restored, skipped = [], []
        for cid, want in NAMES.items():
            c = Customer.query.filter_by(id=cid, agency_id=AGENCY_ID).first()
            if not c:
                skipped.append((cid, "customer not found"))
                continue
            cur = (c.first_name or "").strip()
            if cur == want:
                continue                      # already restored
            # gate: current name must be the same name minus the initial
            if cur != want.split(" ")[0]:
                skipped.append((cid, f"first_name is {cur!r}, expected {want.split(' ')[0]!r}"))
                continue
            restored.append((cid, cur, want, c.last_name))
            if apply:
                c.first_name = want
                c.full_name = f"{want} {c.last_name}".strip()

        print(f"BCBS merge middle-initial restore — {'APPLY' if apply else 'DRY RUN'}")
        print(f"  to restore: {len(restored)}")
        print(f"  skipped   : {len(skipped)}\n")
        for cid, cur, want, last in restored[:60]:
            print(f"  {cid:>6}  {cur} {last}  ->  {want} {last}")
        for cid, why in skipped:
            print(f"  SKIP {cid}: {why}")

        if not apply:
            print("\nDry run — nothing written. Re-run with --apply.")
            return
        db.session.commit()
        print(f"\nAPPLIED: {len(restored)} names restored.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
