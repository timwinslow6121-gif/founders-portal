"""Dedupe duplicate active policies — collapse the same enrollment that came in twice.

A customer can hold only ONE active policy per COVERAGE CATEGORY (Part C = MA/MAPD, PDP,
Medigap, IDVH, hospital-indemnity). Two active policies for the SAME linked plan bucket
(same customer + plan_id) are the SAME enrollment ingested under two different member_id
formats (e.g. Aetna: an MBI-keyed BOB row + an NG-id commission row; Humana: two PID rows).
This collapses each such pair into ONE policy.

Identity model (Tim): the MBI identifies the PERSON (like an SSN), the member_id identifies
the POLICY (the carrier's own policy/enrollment number). Keep BOTH — never lose either:
  - survivor.member_id = the carrier policy id (prefer the row that has PAYMENTS + a real
    carrier member_id, so commission files keep matching it)
  - survivor.mbi       = the person MBI (filled from whichever row has it)
The loser's PolicyPayments reattach to the survivor.

SAFETY: only auto-merges pairs that share the EXACT effective date (same enrollment). A
same-plan pair with DIFFERENT effective dates (possible re-enrollment) is HELD for review.
Read-only unless --apply. DB backup + dry-run first.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/dedupe_duplicate_policies.py \
      --agency 1 [--apply]
"""
import argparse
import re
from collections import defaultdict

from app import create_app
from app.extensions import db
from app.models import Policy, PolicyPayment

_MBI_RE = re.compile(r"^[0-9][0-9A-Z]{10}$")


def _looks_mbi(v):
    return bool(_MBI_RE.match((v or "").strip().upper()))


def _payment_count(pid):
    return PolicyPayment.query.filter_by(policy_id=pid).count()


def _pick_survivor(pols):
    """Prefer the row that carries the carrier POLICY id + the money: (1) has payments,
    (2) has a non-MBI (carrier) member_id, (3) has an import_batch, (4) lowest id."""
    def score(p):
        return (_payment_count(p.id), 0 if _looks_mbi(p.member_id) else 1,
                1 if p.import_batch_id else 0, -p.id)
    return max(pols, key=score)


def dedupe(agency_id, apply=False):
    counts = {"merged_pairs": 0, "policies_removed": 0, "held_diff_eff": 0,
              "payments_moved": 0}
    # group active policies by (customer_id, plan_id) — same linked bucket = same enrollment
    groups = defaultdict(list)
    q = (Policy.query
         .filter(Policy.agency_id == agency_id, Policy.status == "active",
                 Policy.plan_id.isnot(None)))
    for p in q.all():
        groups[(p.customer_id, p.plan_id)].append(p)

    for (_cust, _plan), pols in groups.items():
        if len(pols) < 2:
            continue
        # only merge the subset that shares the exact effective date
        by_eff = defaultdict(list)
        for p in pols:
            by_eff[p.effective_date].append(p)
        for eff, same in by_eff.items():
            if len(same) < 2:
                continue
            survivor = _pick_survivor(same)
            losers = [p for p in same if p.id != survivor.id]
            counts["merged_pairs"] += 1
            counts["policies_removed"] += len(losers)
            # survivor keeps its member_id (policy id); fill its mbi from any loser if blank
            if not (survivor.mbi or "").strip():
                for l in losers:
                    if (l.mbi or "").strip():
                        if apply:
                            survivor.mbi = l.mbi
                        break
            for l in losers:
                pays = PolicyPayment.query.filter_by(policy_id=l.id).all()
                counts["payments_moved"] += len(pays)
                if apply:
                    for pp in pays:
                        pp.policy_id = survivor.id
                    db.session.delete(l)
        # any same-plan rows left with DIFFERENT eff dates → held for review
        distinct_effs = {p.effective_date for p in pols}
        if len(distinct_effs) > 1:
            counts["held_diff_eff"] += 1

    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = dedupe(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] duplicate-policy dedupe, agency {args.agency}:")
        print(f"  merged pairs:        {res['merged_pairs']}")
        print(f"  policies removed:    {res['policies_removed']}")
        print(f"  payments reattached: {res['payments_moved']}")
        print(f"  held (diff eff date, review): {res['held_diff_eff']}")


if __name__ == "__main__":
    main()
