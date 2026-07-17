"""Resume the no-MBI dob_match/shared_id merge, wrapping each cluster in no_autoflush
so the keeper-adopts-mbi + donor-clears-mbi land in ONE flush (avoids the
ix_customers_mbi UniqueViolation that stopped the first run mid-batch on the
3-way 'Annie Maready' cluster). Dry-run by default; --apply to write.

The underlying merge_customers already clears the donor's MBI (_UNIQUE_FILL_FIELDS),
but a mid-function autoflush (from the synchronize_session=False bulk updates) can
flush the keeper's new MBI to Postgres BEFORE the donor-clear flushes → transient
duplicate. no_autoflush defers all flushes to the explicit commit, so both changes
are visible atomically. Same fix pattern as the UHC commission-resolver autoflush bug.

Run on VPS: FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/merge_no_mbi_clusters_safe.py [--apply]
"""
import sys
from app import create_app
from app.extensions import db
from app.dedup import find_no_mbi_clusters
from app.customers import merge_customers

QUALIFYING = {"dob_match", "shared_id"}


def main(apply):
    app = create_app()
    with app.app_context():
        aid = app.config.get("DEFAULT_AGENCY_ID", 1)
        clusters = [c for c in find_no_mbi_clusters(aid) if c.signal in QUALIFYING]
        print(f"{'APPLY' if apply else 'DRY-RUN'} — {len(clusters)} qualifying clusters remaining\n")
        merged = 0
        for cl in clusters:
            # de-dupe member_ids and drop the keeper if it appears in its own member list
            losers = [i for i in dict.fromkeys(cl.member_ids) if i != cl.keeper_id]
            if not losers:
                continue
            print(f"  keeper {cl.keeper_id} <- {losers} [{cl.signal}]")
            if apply:
                with db.session.no_autoflush:
                    res = merge_customers(cl.keeper_id, losers, aid, "dedup_no_mbi_safe")
                if not res.get("ok"):
                    print(f"    ⚠ merge FAILED: {res.get('error')} — rolling back this cluster, continuing")
                    db.session.rollback()
                    continue
                db.session.commit()
                merged += res.get("merged", 0)
        print(f"\n{'COMMITTED' if apply else 'DRY-RUN'} — merged {merged} loser rows across {len(clusters)} clusters.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
