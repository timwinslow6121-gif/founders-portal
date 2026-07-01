"""Collapse no-MBI duplicate clusters that qualify for an unattended merge
(signal dob_match or shared_id). Dry-run by default; pass --apply to write.
NEVER touches name_only or conflict clusters. Back up the DB before --apply.

Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/merge_no_mbi_clusters.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.dedup import find_no_mbi_clusters
from app.customers import merge_customers
from app.models import Agency, User

QUALIFYING = {"dob_match", "shared_id"}


def main(apply=False):
    app = create_app()
    with app.app_context():
        actor = User.query.filter_by(is_admin=True).first()
        if not actor:
            print("ERROR: No admin user found. Cannot proceed.")
            return

        total_merged = 0
        total_filled = 0
        total_skipped = 0

        for ag in Agency.query.all():
            clusters = [c for c in find_no_mbi_clusters(ag.id) if c.signal in QUALIFYING]
            print(f"agency {ag.id}: {len(clusters)} qualifying clusters")
            for cl in clusters:
                losers = [i for i in cl.member_ids if i != cl.keeper_id]
                print(f"  keeper {cl.keeper_id} <- {losers} [{cl.signal}]")
                if apply:
                    res = merge_customers(cl.keeper_id, losers, ag.id, actor)
                    if res["ok"]:
                        db.session.commit()
                        merged = res.get("merged", 0)
                        filled = res.get("filled", 0)
                        print(f"    merged {merged}, filled {filled}")
                        total_merged += merged
                        total_filled += filled
                    else:
                        db.session.rollback()
                        print(f"    SKIPPED: {res['error']}")
                        total_skipped += 1

        if apply:
            print(f"\nAPPLIED — merged {total_merged} records, filled {total_filled} fields, skipped {total_skipped}.")
        else:
            print(f"\nDRY-RUN — nothing committed. Re-run with --apply to commit.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
