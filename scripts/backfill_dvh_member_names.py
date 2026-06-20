"""
scripts/backfill_dvh_member_names.py

One-time backfill: UHC DVH Manual Payment quarantine rows were stored with an
empty member_name (the name lives inside the action string, e.g. "... for JANA
BENSON, State: NC ..."). The parser now extracts it on upload; this fills the
name on rows already imported so they stop showing as "(unnamed)".

Idempotent. Dry-run by default; pass --apply to write.

Run on VPS:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
                 scripts/backfill_dvh_member_names.py [--apply]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem
from app.commission.ledger import _uhc_dvh_member

APPLY = "--apply" in sys.argv

app = create_app()

with app.app_context():
    # DVH/manual rows with no member name (the name is in payment_type/action).
    rows = (CommissionLineItem.query
            .filter(CommissionLineItem.carrier == "UHC",
                    CommissionLineItem.payment_type.ilike("%for %State%"))
            .filter(db.or_(CommissionLineItem.member_name.is_(None),
                           CommissionLineItem.member_name == ""))
            .all())

    fixed = 0
    for li in rows:
        name = _uhc_dvh_member(li.payment_type or "")
        if not name:
            continue
        print(f"  line {li.id} ({li.carrier} {li.period_label}) -> member '{name}'")
        li.member_name = name
        fixed += 1

    print(f"\n{len(rows)} candidate rows; {fixed} would get a member name.")
    if APPLY:
        db.session.commit()
        print("APPLIED — names written.")
    else:
        db.session.rollback()
        print("DRY RUN — nothing written. Re-run with --apply to commit.")
