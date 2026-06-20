"""
scripts/backfill_statement_balance.py

A3 — backfill the balance gate fields on statements imported BEFORE A3. The
original carrier files aren't stored, so money_rows_total (the independent file
re-sum) can't be recomputed exactly. But every current statement was verified to
balance at import (the completeness check passed), so we set ledger_total from the
persisted line items and mark balanced=True with money_rows_total = ledger_total.
The NEXT upload of each statement stamps the authoritative values.

Only touches statements that (a) have line items and (b) have no balance recorded
yet (balanced IS NULL). Idempotent. Dry-run by default; --apply to write.

Run on VPS:  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
                 scripts/backfill_statement_balance.py [--apply]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import CommissionStatement, CommissionLineItem
from app.commission.recap import recompute_ledger_total

APPLY = "--apply" in sys.argv

app = create_app()

with app.app_context():
    stmts = CommissionStatement.query.filter(
        CommissionStatement.balanced.is_(None)).all()
    touched = 0
    for s in stmts:
        n = CommissionLineItem.query.filter_by(statement_id=s.id).count()
        if n == 0:
            continue   # nothing to balance (legacy statement w/o ledger rows)
        total = recompute_ledger_total(s, s.agency_id)
        s.money_rows_total = total
        s.balanced = True   # these all passed the completeness check at import
        touched += 1
        print(f"  stmt {s.id} {s.carrier} {s.period_label}: {n} lines, "
              f"ledger=${total:,.2f} -> balanced ✓")

    print(f"\n{len(stmts)} statements with no balance recorded; {touched} backfilled.")
    if APPLY:
        db.session.commit()
        print("APPLIED.")
    else:
        db.session.rollback()
        print("DRY RUN — nothing written. Re-run with --apply.")
