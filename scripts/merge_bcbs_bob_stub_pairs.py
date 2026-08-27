"""Merge the BCBS BOB-import duplicates created 2026-08-27.

Rebekah's Aug-2026 BCBS book_Of_business.csv created 49 new customers. 46 of
them are the SAME PERSON as a pre-existing legacy BCBS stub: the stubs came
from commission data, carry policies, but have NO MBI and NO DOB — so
_upsert_customer_from_policy (which matches on MBI first) could not find them
and created fresh records instead. This is the known "no-MBI carriers must
match-existing first" failure mode, meeting BCBS's first real BOB.

  NEW  14866  Opal Abernathy     dob 1948-11-10  mbi 8A21FN8FH27   (1 policy)
  OLD   2249  Opal S. Abernathy  dob (null)      mbi (null)        (1 policy)

KEEPER = the NEW record (has MBI + DOB + full address from the BOB).
LOSER  = the legacy stub (its policies/payments/AOR reattach to the keeper).

SAFETY GATES — a pair is only merged when ALL hold:
  1. Same last name (exact, case-insensitive).
  2. First names agree on the first 3 characters (handles "Opal" vs "Opal S.").
  3. NO contradictory DOB — the stub's DOB is NULL or equal to the keeper's.
     A different real DOB means a different person and is REFUSED.
  4. NO contradictory MBI.
  5. Exactly ONE surviving candidate after gates 3-4. If two stubs still
     qualify for the same keeper the pair is REFUSED for human review —
     never guess which one.
  6. Both records are in the same agency.

Ambiguity is resolved by the gates, not by ranking: "Betty Beaver" matched
three candidates, two of which gate 3 (different DOB) and name mismatch
eliminate, leaving one. If gates ever leave two, the pair is skipped.

Uses the shared merge_customers engine (reattaches policies/payments/AOR/
notes/line-items; fill-blanks-only; refuses contradictions; audited).

Dry-run by default; --apply to write.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/merge_bcbs_bob_stub_pairs.py [--apply]
"""
import sys
from datetime import date

from app import create_app
from app.extensions import db
from app.models import Customer, Policy
from app.customers import merge_customers

AGENCY_ID = 1
IMPORT_DATE = date(2026, 8, 27)   # the BCBS BOB import that created the dupes

# Human decisions for pairs the gates correctly refuse.
# 14888 "Betty Beaver" (dob 1949-06-20) matched two stubs that both survive the
# gates — "Betty A. Beaver" and "Bethany B. Beaver", neither carrying a DOB.
# Tim confirmed 2026-08-27: it is Betty A. (2252); Bethany B. is a different
# person and must be left alone.
MANUAL_PAIRS = {
    14888: 2252,
}


def _norm(s):
    return (s or "").strip().upper()


def find_pairs(agency_id, import_date):
    """Return (pairs, refused). pairs = [(keeper, loser)]."""
    new_rows = (Customer.query
                .filter(Customer.agency_id == agency_id)
                .filter(db.func.date(Customer.created_at) == import_date)
                .all())

    pairs, refused = [], []
    for n in new_rows:
        cands = (Customer.query
                 .filter(Customer.agency_id == agency_id)
                 .filter(Customer.id != n.id)
                 .filter(db.func.upper(Customer.last_name) == _norm(n.last_name))
                 .filter(db.func.date(Customer.created_at) < import_date)
                 .all())

        # gate 2: first-name agreement on the first 3 characters
        cands = [c for c in cands
                 if _norm(c.first_name)[:3] and _norm(c.first_name)[:3] == _norm(n.first_name)[:3]]

        # gate 3: no contradictory DOB
        cands = [c for c in cands if not (c.dob and n.dob and c.dob != n.dob)]

        # gate 4: no contradictory MBI
        cands = [c for c in cands if not (c.mbi and n.mbi and c.mbi != n.mbi)]

        if not cands:
            continue

        # A human decision overrides ambiguity — but only to a candidate that
        # already passed every gate, so it can never resurrect a refused match.
        chosen_id = MANUAL_PAIRS.get(n.id)
        if chosen_id is not None:
            chosen = next((c for c in cands if c.id == chosen_id), None)
            if chosen is None:
                refused.append((n, cands,
                                f"MANUAL_PAIRS names {chosen_id}, which did not pass the gates"))
                continue
            pairs.append((n, chosen))
            continue

        if len(cands) > 1:
            refused.append((n, cands, "ambiguous: %d candidates survive the gates" % len(cands)))
            continue
        pairs.append((n, cands[0]))
    return pairs, refused


def main(apply):
    app = create_app()
    with app.app_context():
        pairs, refused = find_pairs(AGENCY_ID, IMPORT_DATE)

        print(f"BCBS BOB stub merge — {'APPLY' if apply else 'DRY RUN'}")
        print(f"  merge pairs found : {len(pairs)}")
        print(f"  refused (ambiguous): {len(refused)}\n")

        for keeper, loser in pairs:
            kp = Policy.query.filter_by(customer_id=keeper.id).count()
            lp = Policy.query.filter_by(customer_id=loser.id).count()
            print(f"  keep {keeper.id:>6} {keeper.first_name} {keeper.last_name} "
                  f"(dob {keeper.dob}, mbi {keeper.mbi}, {kp} pol) "
                  f"<- {loser.id} '{loser.first_name} {loser.last_name}' "
                  f"(dob {loser.dob or '-'}, {lp} pol)")

        if refused:
            print("\n  REFUSED — need a human decision:")
            for n, cands, why in refused:
                print(f"    {n.id} {n.first_name} {n.last_name} (dob {n.dob}) — {why}")
                for c in cands:
                    print(f"        candidate {c.id} '{c.first_name} {c.last_name}' dob={c.dob or '-'}")

        if not apply:
            print("\nDry run — nothing written. Re-run with --apply.")
            return

        merged = 0
        for keeper, loser in pairs:
            merge_customers(keeper.id, [loser.id], AGENCY_ID, actor="bcbs_bob_stub_merge")
            merged += 1
        db.session.commit()
        print(f"\nAPPLIED: {merged} merges committed.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
