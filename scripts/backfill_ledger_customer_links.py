"""
One-time backfill: link existing CommissionLineItem rows to their Customer.

Repairs the 641 rows left unlinked by the pre-fix `persist_line_items` (single-tier
MBI lookup that also erased links on re-upload). Uses the SAME resolution order as
the live path, so the backfill and future uploads cannot disagree.

TOUCHES `customer_id` ONLY -- never raw_amount, split_rate, classification, or
agent_id. Money is provably unchanged.

Usage (on the VPS):
    PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
        scripts/backfill_ledger_customer_links.py            # dry run (default)
    PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
        scripts/backfill_ledger_customer_links.py --apply
"""

import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem
from app.commission.backlink import build_backlink_context, resolve_customer_id

# Only rows that represent real member money. Overrides/HRA are intentionally
# excluded -- they mirror the same classification filter the /unassigned page uses.
_CLASSES = ["agent_commission", "chargeback"]


def backfill_ledger_links(agency_id, apply=False, sample=0):
    ctx = build_backlink_context(agency_id)
    rows = (CommissionLineItem.query
            .filter(CommissionLineItem.agency_id == agency_id,
                    CommissionLineItem.customer_id.is_(None),
                    CommissionLineItem.classification.in_(_CLASSES))
            .all())
    stats = {"examined": len(rows), "resolved": 0, "unresolved": 0, "by_carrier": {}}
    shown = 0
    for r in rows:
        cid = resolve_customer_id(
            ctx, source_ref=r.source_ref, carrier=r.carrier, mbi=r.mbi,
            carrier_member_id=r.carrier_member_id, member_name=r.member_name)
        if cid is None:
            stats["unresolved"] += 1
            continue
        stats["resolved"] += 1
        stats["by_carrier"][r.carrier] = stats["by_carrier"].get(r.carrier, 0) + 1
        if sample and shown < sample:
            print(f"  {r.carrier:12} {(r.member_name or '(none)')[:28]:28} "
                  f"${r.raw_amount:>10.2f}  -> customer {cid}")
            shown += 1
        if apply:
            r.customer_id = cid
    if apply:
        db.session.commit()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the links (default is a dry run)")
    ap.add_argument("--agency-id", type=int, default=1)
    ap.add_argument("--sample", type=int, default=15,
                    help="print this many proposed links for eyeballing")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        print(f"{'APPLYING' if args.apply else 'DRY RUN'} "
              f"(agency {args.agency_id})\n")
        s = backfill_ledger_links(args.agency_id, apply=args.apply,
                                  sample=args.sample)
        print(f"\nexamined   : {s['examined']}")
        print(f"resolved   : {s['resolved']}")
        print(f"unresolved : {s['unresolved']}")
        for carrier, n in sorted(s["by_carrier"].items(),
                                 key=lambda kv: -kv[1]):
            print(f"   {carrier:14} {n}")
        if not args.apply:
            print("\n(dry run -- nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
