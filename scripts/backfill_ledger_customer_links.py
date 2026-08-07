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
from app.models import CommissionLineItem, Customer
from app.commission.backlink import build_backlink_context, resolve_customer_id
from app.commission.payments import _norm

# Only rows that represent real member money. Overrides/HRA are intentionally
# excluded -- they mirror the same classification filter the /unassigned page uses.
_CLASSES = ["agent_commission", "chargeback"]


def _surnames_agree(member_name, customer_full_name):
    """Does the ledger row's member name agree with the customer it would link to?

    A SAFETY GATE, not a matcher. The resolver's step-1 (payment sibling) inherits
    whatever the ingest resolver decided, and on messy historical records that can
    be wrong -- a real example found on prod: two identical `COUCHELL, JOHN` rows,
    one resolving to John Couchell (right) and one to Andrea Horstmann (WRONG).
    A wrong customer_id is invisible (money still balances -- only attribution
    moves) and permanent (the never-erase rule means re-uploads never correct it),
    so a link whose name disagrees is REFUSED and left NULL for a human.

    Extracts the SURNAME from each side and requires them to be equal. Comparing
    whole-token SETS would be too loose -- two different people sharing only a
    first name ("SMITH, JOHN" vs "John Couchell") would pass. Comparing by
    position is impossible, because the two sides use different orders: the ledger
    holds carrier formats ("Robinson,Keith M", "HELMS TERESSA D", "PRESSON, ROBIN")
    while the portal stores "First M. Last".

    payments._norm is deliberately NOT reused here: it is built for the carrier
    side and mangles the portal side ("Keith M. Robinson" -> "m. keith").

    Surname rules, matching the formats actually present in this data:
      - comma form ("Robinson,Keith M" / "PRESSON, ROBIN") -> text before the comma
        is unambiguously the surname.
      - space form is AMBIGUOUS: the ledger holds both "HELMS TERESSA D"
        (LAST FIRST M) and "Mary Earnhardt" (First Last), and nothing in the row
        says which. So a comma-less side yields BOTH candidate ends, and agreement
        means the two sides share a surname under some consistent reading.
    Single-character tokens (middle initials) are never candidates, so a shared
    initial can never carry a match. Requiring an end token -- rather than any
    token -- is what keeps "SMITH, JOHN" from matching "John Couchell".
    """
    # Generational suffixes are part of neither side's surname and appear
    # inconsistently ("Koman Jr,Charles" vs "Charles Koman Jr").
    _SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

    def candidates(s):
        s = str(s or "").strip()
        if not s:
            return set()
        if "," in s:
            # Comma form: everything before the comma is the surname, which may
            # itself be compound ("Ortiz Maldonado,Orlando"). Yield each word so a
            # compound surname still meets the other side's tokens.
            head = s.split(",", 1)[0]
            toks = [t.strip(".").lower() for t in head.split()]
        else:
            toks = [t.strip(".").lower() for t in s.split()]
        toks = [t for t in toks
                if len(t) > 1 and t not in _SUFFIXES]   # drop initials + Jr/Sr
        if not toks:
            return set()
        if "," in s:
            return set(toks)                # whole (possibly compound) surname
        return {toks[0], toks[-1]}          # ambiguous order -> both ends

    a, b = candidates(member_name), candidates(customer_full_name)
    if not a or not b:
        return False                      # no name to check -> refuse
    return bool(a & b)


def backfill_ledger_links(agency_id, apply=False, sample=0):
    ctx = build_backlink_context(agency_id)
    rows = (CommissionLineItem.query
            .filter(CommissionLineItem.agency_id == agency_id,
                    CommissionLineItem.customer_id.is_(None),
                    CommissionLineItem.classification.in_(_CLASSES))
            .all())
    stats = {"examined": len(rows), "resolved": 0, "unresolved": 0,
             "refused_name_mismatch": 0, "by_carrier": {}}
    shown = 0
    for r in rows:
        cid = resolve_customer_id(
            ctx, statement_id=r.statement_id, source_ref=r.source_ref,
            carrier=r.carrier, mbi=r.mbi,
            carrier_member_id=r.carrier_member_id, member_name=r.member_name)
        if cid is None:
            stats["unresolved"] += 1
            continue
        cust = db.session.get(Customer, cid)
        if cust is None or not _surnames_agree(r.member_name, cust.full_name):
            stats["refused_name_mismatch"] += 1
            print(f"  REFUSED (name mismatch): {r.carrier} | "
                  f"{r.member_name or '(none)'} -> #{cid} "
                  f"{cust.full_name if cust else '(missing customer)'}")
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
        print(f"REFUSED (name mismatch) : {s['refused_name_mismatch']}")
        for carrier, n in sorted(s["by_carrier"].items(),
                                 key=lambda kv: -kv[1]):
            print(f"   {carrier:14} {n}")
        if not args.apply:
            print("\n(dry run -- nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
