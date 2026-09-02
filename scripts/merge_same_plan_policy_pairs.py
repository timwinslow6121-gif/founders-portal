"""Merge duplicate ACTIVE policies for the same customer + same plan bucket.

WHERE THESE COME FROM: merging two duplicate CUSTOMERS moves both their
policies onto one person -- which is what creates the duplicate POLICY pair.
Tim merged 46 duplicate customers on 2026-09-01 and 46 duplicate policy pairs
appeared behind them (Tiwana Burch holding HumanaChoice PPO H5525-070 twice).
The customer merge does not collapse policies, so this is the second half of
the same cleanup.

The two rows are one enrollment keyed two ways -- the carrier's BOB id
('H76593494') and the commission file's internal id ('409620038') -- with no
shared MBI to bridge them, which is why ingest could not match them.

SURVIVOR: the BOB-sourced row (it has an import_batch_id). Its member_id is the
agent-facing identifier; the commission file's numeric PID is a Humana-internal
payment key useless to agents (Tim, 2026-08-28). Earliest effective date wins.
The loser's payments reattach.

GATES -- refuse rather than guess. A wrong merge is invisible (money still ties)
and permanent:
  1. same customer, same carrier, same plan bucket, both active
  2. identical effective dates (all 47 real pairs have this; a differing date
     could be a genuine re-enrollment and is left for a human)
  3. no term date on either row
  4. exactly one side has an import_batch_id, so the survivor is unambiguous
  5. at most one side carries payments -- if BOTH are paid, the carrier is
     paying two policies and this is not a duplicate

Dry-run by default; --apply to write.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/merge_same_plan_policy_pairs.py [--carrier X] [--apply]
"""
import sys
from collections import Counter

from app import create_app
from app.extensions import db
from app.models import Customer, Plan, Policy, PolicyPayment

AGENCY_ID = 1


def main(apply, carrier):
    app = create_app()
    with app.app_context():
        plans = {p.id: p for p in Plan.query.filter_by(agency_id=AGENCY_ID).all()}
        a_, b_ = db.aliased(Policy), db.aliased(Policy)
        q = (db.session.query(a_, b_)
             .join(b_, db.and_(a_.customer_id == b_.customer_id,
                               a_.plan_id == b_.plan_id, a_.id < b_.id))
             .filter(a_.agency_id == AGENCY_ID, b_.agency_id == AGENCY_ID,
                     a_.status == "active", b_.status == "active",
                     a_.plan_id.isnot(None), a_.customer_id.isnot(None)))
        if carrier:
            q = q.filter(a_.carrier == carrier, b_.carrier == carrier)

        merges, refused = [], []
        for a, b in q.all():
            cust = Customer.query.get(a.customer_id)
            plan = plans.get(a.plan_id)
            label = f"{cust.full_name if cust else '?'} / {plan.plan_name if plan else a.plan_id}"

            if a.carrier != b.carrier:
                refused.append((label, "carrier mismatch")); continue
            if a.term_date or b.term_date:
                refused.append((label, "a row carries a term date")); continue
            if a.effective_date != b.effective_date:
                refused.append((label, "effective dates differ — could be a re-enrollment"))
                continue

            pa = PolicyPayment.query.filter_by(policy_id=a.id).count()
            pb = PolicyPayment.query.filter_by(policy_id=b.id).count()
            if pa and pb:
                refused.append((label, "BOTH rows carry payments — not a duplicate"))
                continue

            if a.import_batch_id and not b.import_batch_id:
                keep, drop, moved = a, b, pb
            elif b.import_batch_id and not a.import_batch_id:
                keep, drop, moved = b, a, pa
            else:
                refused.append((label, "cannot tell which row came from the BOB"))
                continue

            merges.append((label, keep, drop, moved))

            if apply:
                if not keep.mbi and drop.mbi:
                    keep.mbi = drop.mbi
                dates = [d for d in (keep.effective_date, drop.effective_date) if d]
                if dates:
                    keep.effective_date = min(dates)
                if not keep.agent_id and drop.agent_id:
                    keep.agent_id = drop.agent_id
                PolicyPayment.query.filter_by(policy_id=drop.id).update(
                    {"policy_id": keep.id}, synchronize_session=False)
                db.session.delete(drop)

        print(f"same-plan policy merge — {'APPLY' if apply else 'DRY RUN'}"
              f"{f' [{carrier}]' if carrier else ''}")
        print(f"  merge : {len(merges)}")
        print(f"  refuse: {len(refused)}\n")
        for label, keep, drop, moved in merges[:20]:
            print(f"  {label}")
            print(f"      keep {keep.id} member={keep.member_id!r} eff={keep.effective_date}")
            print(f"      drop {drop.id} member={drop.member_id!r} ({moved} payments move)")
        if len(merges) > 20:
            print(f"  … and {len(merges)-20} more")
        for why, n in Counter(r[1] for r in refused).most_common():
            print(f"  REFUSED x{n}: {why}")

        if not apply:
            print("\nDry run — nothing written.")
            return
        db.session.commit()
        print(f"\nAPPLIED: {len(merges)} policy pairs merged.")


if __name__ == "__main__":
    av = sys.argv
    main("--apply" in av, av[av.index("--carrier") + 1] if "--carrier" in av else None)
