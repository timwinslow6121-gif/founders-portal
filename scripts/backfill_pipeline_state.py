"""
Give every living customer a PipelineState row.

Dry run by default. Idempotent: re-running creates 0 -- pipeline_state has a
UNIQUE constraint on customer_id, so a non-idempotent run would not merely
double-count, it would crash.

Deceased customers are skipped: they must never enter a work queue (migration
043). The test is app.models.is_contactable(), the portal's single suppression
seam -- never deceased_date directly, so a future suppression rule lands in one
place and this script inherits it.

Counted buckets are mutually exclusive and sum to the customers considered:
a customer who already has a row is counted there and nowhere else, even if
they are also deceased -- their row already exists and there is nothing to do.

Usage:
  ./venv/bin/python3 scripts/backfill_pipeline_state.py            # dry run
  ./venv/bin/python3 scripts/backfill_pipeline_state.py --apply
  ./venv/bin/python3 scripts/backfill_pipeline_state.py --apply --agency 1
"""
import sys, os, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extensions import db
from app.models import Customer, PipelineState, is_contactable


def run(apply=False, agency_id=1):
    """Create a PipelineState for every living customer in this agency.

    Returns {created, skipped_existing, skipped_deceased}. In a dry run
    `created` is what WOULD be created and nothing is written.
    """
    existing = {
        r[0] for r in db.session.query(PipelineState.customer_id)
                                .filter(PipelineState.agency_id == agency_id)
                                .all()
    }
    customers = Customer.query.filter_by(agency_id=agency_id).all()

    created = skipped_existing = skipped_deceased = 0
    for c in customers:
        if c.id in existing:
            skipped_existing += 1
            continue
        if not is_contactable(c):
            skipped_deceased += 1
            continue
        created += 1
        if apply:
            db.session.add(PipelineState(
                agency_id=agency_id, customer_id=c.id,
                track="renewal", stage="contact",
            ))
    if apply:
        db.session.commit()

    return {"created": created,
            "skipped_existing": skipped_existing,
            "skipped_deceased": skipped_deceased}


if __name__ == "__main__":
    from app import create_app
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agency", type=int, default=1)
    args = ap.parse_args()
    with create_app().app_context():
        res = run(apply=args.apply, agency_id=args.agency)
        print(f"{'APPLY' if args.apply else 'DRY RUN'} -- pipeline_state backfill "
              f"(agency {args.agency})")
        print(f"  created:           {res['created']}")
        print(f"  already had one:   {res['skipped_existing']}")
        print(f"  skipped deceased:  {res['skipped_deceased']}")
        if not args.apply:
            print("\nNothing was written. Re-run with --apply.")
