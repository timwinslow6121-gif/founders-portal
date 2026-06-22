# scripts/recover_policy_names.py
"""Link 2: recover names for no-name active policies (ledger-first via
recover_policy_name). Dry-run default; --apply commits. Back up DB first.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/recover_policy_names.py [--apply]
"""
import sys
from collections import Counter
from sqlalchemy import or_
from app import create_app
from app.extensions import db
from app.models import Policy
from app.identity import recover_policy_name

def main(apply):
    app = create_app()
    with app.app_context():
        rows = (Policy.query.filter(Policy.status == "active",
                or_(Policy.first_name.is_(None), Policy.first_name == ""),
                or_(Policy.last_name.is_(None), Policy.last_name == "")).all())
        out = Counter()
        for p in rows:
            r = recover_policy_name(p, p.agency_id)
            out[r["action"]] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — {len(rows)} no-name policies:")
        for a, n in out.most_common():
            print(f"  {n:5d}  {a}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
