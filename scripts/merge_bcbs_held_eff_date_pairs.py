"""Merge the 5 BCBS policy pairs the generic dedupe HELD for different effective dates.

scripts/dedupe_duplicate_policies.py auto-merges same-plan pairs only when the
effective dates match, and holds the rest — a different date could be a genuine
re-enrollment. These 5 were reviewed by Tim on 2026-08-27 and are all the SAME
enrollment, keyed two ways:

  legacy row  = commission-sourced, carrier member number, NO MBI, older eff date
  BOB row     = today's book of business, MBI, corrected/current eff date

  Susan M. Compton  H3449-012  Medical Only     2024-01-01 -> 2025-04-01
  Sandra C. Graham  H3449-023  Essential Plus   2025-11-01 -> 2026-01-01
  Cindy M. Head     H3449-012  Medical Only     2024-01-01 -> 2025-01-01
  Donna B. Spry     H3449-012  Medical Only     2024-01-01 -> 2025-02-01
  Rachel Morrison   (Medigap)  MedSupp G 2019   2025-11-01 -> 2026-06-01

Morrison needed a domain call: Medigap is a lane where multiple active policies
ARE legitimate, so a 7-month gap looks like a new policy. Tim (2026-08-27): a
Medigap RATE INCREASE reissues the effective date on the SAME policy — both rows
are Plan G 2019, so it is one policy with a new date, not two.

RESULT PER PAIR — keep BOTH identifiers, per the identity model (MBI = the
person, member_id = the policy):
  survivor.member_id     = the carrier policy number (from the legacy row)
  survivor.mbi           = the MBI (from the BOB row)
  survivor.effective_date= the BOB date (authoritative, current)
The loser's payments/line-items reattach to the survivor.

SAFETY: each pair is addressed by explicit policy ids; the script re-verifies
same customer, same carrier, same plan_id, both active before touching anything,
and refuses the pair otherwise.

Dry-run by default; --apply to write.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/merge_bcbs_held_eff_date_pairs.py [--apply]
"""
import sys

from app import create_app
from app.extensions import db
from app.models import Policy, PolicyPayment

AGENCY_ID = 1

# (legacy_policy_id, bob_policy_id, expected_customer_id, label)
PAIRS = [
    (6126, 16122, 14876, "Susan M. Compton  H3449-012"),
    (6131, 16148, 14902, "Sandra C. Graham  H3449-023"),
    (6132, 16119, 14873, "Cindy M. Head     H3449-012"),
    (6153, 16127, 14881, "Donna B. Spry     H3449-012"),
    (6143, 16158, 14911, "Rachel Morrison   MedSupp G 2019"),
]


def main(apply):
    app = create_app()
    with app.app_context():
        merged, refused = [], []

        for legacy_id, bob_id, cust_id, label in PAIRS:
            legacy = Policy.query.filter_by(id=legacy_id, agency_id=AGENCY_ID).first()
            bob = Policy.query.filter_by(id=bob_id, agency_id=AGENCY_ID).first()

            if not legacy or not bob:
                refused.append((label, "one of the policies no longer exists"))
                continue
            if legacy.customer_id != cust_id or bob.customer_id != cust_id:
                refused.append((label, "customer_id changed since review"))
                continue
            if legacy.carrier != bob.carrier:
                refused.append((label, "carrier mismatch"))
                continue
            if legacy.plan_id != bob.plan_id:
                refused.append((label, "different plan bucket — NOT the same enrollment"))
                continue
            if legacy.status != "active" or bob.status != "active":
                refused.append((label, "one of the policies is not active"))
                continue

            # CommissionLineItem has no policy_id — it links to the customer,
            # which the earlier customer merge already consolidated.
            pay = PolicyPayment.query.filter_by(policy_id=bob.id).count()
            merged.append((label, legacy, bob, pay))

            if apply:
                # survivor = the LEGACY row: it carries the carrier policy number
                # that commission files match on, plus any existing payments.
                legacy.mbi = bob.mbi or legacy.mbi
                legacy.effective_date = bob.effective_date        # BOB is authoritative
                legacy.plan_name = bob.plan_name or legacy.plan_name
                legacy.term_date = bob.term_date
                legacy.import_batch_id = bob.import_batch_id or legacy.import_batch_id
                if bob.agent_id:
                    legacy.agent_id = bob.agent_id

                PolicyPayment.query.filter_by(policy_id=bob.id).update(
                    {"policy_id": legacy.id}, synchronize_session=False)
                db.session.delete(bob)

        print(f"BCBS held-pair merge — {'APPLY' if apply else 'DRY RUN'}")
        print(f"  pairs to merge: {len(merged)}")
        print(f"  refused       : {len(refused)}\n")
        for label, legacy, bob, pay in merged:
            print(f"  {label}")
            print(f"      keep  {legacy.id} member_id={legacy.member_id} "
                  f"<- takes MBI {bob.mbi} + eff {bob.effective_date}")
            print(f"      drop  {bob.id} (moves {pay} payments)")
        for label, why in refused:
            print(f"  REFUSED {label}: {why}")

        if not apply:
            print("\nDry run — nothing written. Re-run with --apply.")
            return
        db.session.commit()
        print(f"\nAPPLIED: {len(merged)} policy pairs merged.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
