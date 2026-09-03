"""Restore UHC effective dates overwritten by the 2026-09-02 BOB import.

WHAT HAPPENED: UHC's September book of business added four columns the August
export did not have — policyEffectiveDate, contract, segmentId, termReasonCode —
and pre-loaded the 2027 plan year, stamping `2027-01-01` on every member whose
MA/MAPD renews on 1 January. That date is REAL and is UHC's, not ours.

THE BUG IS OURS: `app/upload.py` assigns

    existing.effective_date = rec["effective_date"]

unconditionally, so each policy's true effective date was replaced by the future
one. A member enrolled in 2022 now reads as starting 2027-01-01, and the original
is gone from the policy row. Effective date drives commission type (initial vs
renewal), the AOR timeline and rapid-disenrollment reporting.

Live: 2,037 UHC policies at 2027-01-01. The 2026-09-01 03:15 nightly backup
predates the 00:01 import by ~21 hours and holds the originals.

RESTORE RULE — earliest wins (Tim, 2026-08-28, the Elva Sprouse precedent): a
policy's effective date is when coverage BEGAN, not when the current contract
year took over. Where the backup holds an earlier date than live, restore it.

GATES — refuse rather than guess:
  1. matched by policy id, and the carrier must still be UHC on both sides
  2. member_id must be unchanged (an id that moved is not the same enrollment)
  3. only rows where live > backup are touched — never move a date FORWARD
  4. touches `effective_date` only; no money field, no status, no term date

Dry-run by default; --apply to write.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/restore_uhc_effective_dates.py [--apply]
"""
import os
import sys

from app import create_app
from app.extensions import db
from app.models import Policy
from sqlalchemy import create_engine, text

AGENCY_ID = 1
BACKUP_DB = os.environ.get("BACKUP_DB", "effdate_check")


def main(apply):
    app = create_app()
    with app.app_context():
        url = str(db.engine.url).replace(f"/{db.engine.url.database}", f"/{BACKUP_DB}")
        backup = create_engine(url)
        with backup.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, member_id, effective_date, carrier FROM policies "
                "WHERE agency_id=:a AND carrier='UHC'"), {"a": AGENCY_ID}).fetchall()
        old = {r[0]: (r[1], r[2]) for r in rows}
        print(f"backup rows: {len(old)}")

        restore, refused = [], []
        for p in Policy.query.filter_by(agency_id=AGENCY_ID, carrier="UHC").all():
            prev = old.get(p.id)
            if prev is None:
                continue                      # created after the backup — leave it
            prev_member, prev_eff = prev
            if (p.member_id or "") != (prev_member or ""):
                refused.append((p.id, "member_id changed — not the same enrollment"))
                continue
            if prev_eff is None or p.effective_date is None:
                continue
            if p.effective_date <= prev_eff:
                continue                      # already correct or older — leave it
            restore.append((p, prev_eff))
            if apply:
                p.effective_date = prev_eff

        print(f"{'APPLY' if apply else 'DRY RUN'}")
        print(f"  to restore : {len(restore)}")
        print(f"  refused    : {len(refused)}\n")
        for p, prev in restore[:15]:
            print(f"   pol {p.id:6d} {p.member_id!r:14s} {p.effective_date} -> {prev}")
        if len(restore) > 15:
            print(f"   … and {len(restore)-15} more")
        for pid, why in refused[:10]:
            print(f"   REFUSED pol {pid}: {why}")

        if not apply:
            print("\nDry run — nothing written.")
            return
        db.session.commit()
        print(f"\nAPPLIED: {len(restore)} effective dates restored.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
