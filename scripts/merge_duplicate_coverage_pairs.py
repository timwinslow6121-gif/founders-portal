"""Merge same-plan duplicate policy pairs created by two-ID-namespace ingest.

THE BUG (third instance, after BCBS and Devoted): a carrier's BOB keys a member
one way and its commission file keys the same member another way, and neither
row carries an MBI, so _upsert_customer_from_policy's
(carrier, member_id) -> (carrier, mbi) dedup cannot bridge them and creates a
SECOND active policy for ONE enrollment.

    Humana : BOB 'Humana ID' H57701868   vs  commission 'PID' 154764174
    Devoted: MBI-shaped id               vs  'D…' member locator

SURVIVOR RULE (Tim, 2026-08-28): keep the identifier agents can actually use.
For Humana that is the BOB 'Humana ID' (H…), NOT the numeric PID, which is a
Humana-internal payment key that appears in no agent-facing system. This is
deliberately the OPPOSITE of the BCBS rule, where the carrier member number was
the agent-facing id. The loser's payments reattach to the survivor either way,
so keeping the usable id costs nothing.

The survivor takes the BOB effective date (authoritative and current) and keeps
whichever MBI exists.

GATES — every pair must PROVE it is one enrollment, or it is REFUSED, not
ranked. A wrong merge is invisible (money still ties) and permanent.
  1. same customer, same carrier, same plan bucket, both active
  2. exactly one of the two rows is present in the carrier BOB (the other is
     the commission-sourced twin) -- a pair where BOTH or NEITHER are in the
     BOB is a different animal and is refused
  3. no term_date on either row
  4. surnames agree between the customer and both policy rows
  5. the two rows must not be in DIFFERENT plan buckets (that is coexistence,
     not duplication)

⚠ NOT a gate: equal effective dates, and equal contract codes. Humana renumbers
contracts across a crosswalk (R1390 -> R0110, verified: R1390 is absent from
CMS 2026 data entirely) and reissues effective dates on renewal, so a member
continuously enrolled since 2022 legitimately shows two contracts and two
dates. Requiring either would wrongly split real duplicates.

Dry-run by default; --apply to write. --carrier to limit.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/merge_duplicate_coverage_pairs.py [--carrier Humana] [--apply]
"""
import json
import re
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Plan, Policy, PolicyPayment

AGENCY_ID = 1


def _name_tokens(name):
    """Comparable name tokens, order- and format-agnostic.

    Carriers write the same person three ways in one book:
        'HOWELL REBECCA M'  (Humana commission: LAST FIRST MI, no comma)
        'Howell, Rebecca'   (comma form)
        'Rebecca Howell'    (portal form)
    Taking the last token as the surname picks the MIDDLE INITIAL out of the
    first form, which refused all 142 real pairs on the first dry run. Compare
    on the set of substantive tokens instead, ignoring single letters and
    common suffixes, so any word order agrees.
    """
    if not name:
        return set()
    n = name.replace(",", " ")
    toks = {t.strip(".").lower() for t in n.split()}
    return {t for t in toks
            if len(t) > 1 and t not in {"jr", "sr", "ii", "iii", "iv", "md"}}


def _load_bob_ids(path):
    """member ids present in the carrier's authoritative BOB export."""
    if not path:
        return None
    with open(path) as fh:
        return set(json.load(fh).keys())


def main(apply, carrier, bob_path):
    app = create_app()
    with app.app_context():
        bob_ids = _load_bob_ids(bob_path)
        plans = {p.id: p for p in Plan.query.filter_by(agency_id=AGENCY_ID).all()}

        p1, p2 = db.aliased(Policy), db.aliased(Policy)
        q = (db.session.query(p1, p2)
             .join(p2, db.and_(p1.customer_id == p2.customer_id,
                               p1.plan_id == p2.plan_id,
                               p1.id < p2.id))
             .filter(p1.agency_id == AGENCY_ID, p2.agency_id == AGENCY_ID,
                     p1.status == "active", p2.status == "active",
                     p1.plan_id.isnot(None), p1.customer_id.isnot(None)))
        if carrier:
            q = q.filter(p1.carrier == carrier, p2.carrier == carrier)

        merges, refused = [], []
        for a, b in q.all():
            cust = Customer.query.get(a.customer_id)
            plan = plans.get(a.plan_id)
            label = f"{cust.full_name if cust else '?'} / {plan.plan_name if plan else a.plan_id}"

            if a.carrier != b.carrier:
                refused.append((label, "carrier mismatch")); continue
            if a.term_date or b.term_date:
                refused.append((label, "a row carries a term date")); continue

            # Every row must share at least two substantive name tokens with the
            # customer (surname + given name), which tolerates middle initials,
            # suffixes and word order but still catches a genuine wrong-person link.
            cust_toks = _name_tokens(cust.full_name if cust else "")
            if cust_toks:
                for x in (a, b):
                    xt = _name_tokens(x.full_name)
                    if xt and len(cust_toks & xt) < min(2, len(cust_toks)):
                        refused.append((label, f"name disagreement: {x.full_name!r}"))
                        break
                else:
                    pass
                if refused and refused[-1][0] == label:
                    continue

            if bob_ids is not None:
                in_bob = [x for x in (a, b) if (x.member_id or "").strip() in bob_ids]
                if len(in_bob) != 1:
                    refused.append((
                        label,
                        f"{len(in_bob)} of 2 rows are in the BOB — expected exactly 1"))
                    continue
                keep = in_bob[0]
                drop = b if keep is a else a
            else:
                refused.append((label, "no BOB file supplied — cannot prove survivor"))
                continue

            pays = PolicyPayment.query.filter_by(policy_id=drop.id).count()
            merges.append((label, keep, drop, pays))

            if apply:
                if not keep.mbi and drop.mbi:
                    keep.mbi = drop.mbi
                if drop.effective_date and not keep.effective_date:
                    keep.effective_date = drop.effective_date
                if not keep.agent_id and drop.agent_id:
                    keep.agent_id = drop.agent_id
                PolicyPayment.query.filter_by(policy_id=drop.id).update(
                    {"policy_id": keep.id}, synchronize_session=False)
                db.session.delete(drop)

        print(f"duplicate-coverage merge — {'APPLY' if apply else 'DRY RUN'}"
              f"{f' [{carrier}]' if carrier else ''}")
        print(f"  pairs to merge : {len(merges)}")
        print(f"  refused        : {len(refused)}\n")
        for label, keep, drop, pays in merges[:25]:
            print(f"  {label}")
            print(f"      keep {keep.id} member_id={keep.member_id!r} eff={keep.effective_date}")
            print(f"      drop {drop.id} member_id={drop.member_id!r} eff={drop.effective_date}"
                  f"  (moves {pays} payments)")
        if len(merges) > 25:
            print(f"  … and {len(merges)-25} more")
        print()
        from collections import Counter
        for why, n in Counter(r[1] for r in refused).most_common():
            print(f"  REFUSED x{n}: {why}")

        if not apply:
            print("\nDry run — nothing written. Re-run with --apply.")
            return
        db.session.commit()
        print(f"\nAPPLIED: {len(merges)} pairs merged.")


if __name__ == "__main__":
    av = sys.argv
    main("--apply" in av,
         av[av.index("--carrier") + 1] if "--carrier" in av else None,
         av[av.index("--bob") + 1] if "--bob" in av else None)
