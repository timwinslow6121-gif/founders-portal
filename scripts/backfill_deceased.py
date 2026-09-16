"""scripts/backfill_deceased.py

One-time backfill: mark the members already known to be deceased from files
already on disk, before the deceased-capture feature existed to catch them on
import. DRY RUN BY DEFAULT — pass --apply to write.

Sources (see docs/superpowers/sdd/2026-09-03-member-deceased-capture/task-9-brief.md):
  - UHC May 2026 commission statement:
    docs/Commission DL/_organized/2026-05_cycle/raw/UHC/statement-2813549-20260501 (4).xlsx
  - UHC July 2026 commission statement:
    docs/Commission DL/_organized/2026-07_cycle/Founders_Commission_July_2026/statement-2813549-20260701 (1).xlsx
    Both are read from the 'Commission Transactions' sheet. A row is a death
    when its Term Reason column (index 24) reads "Death" (case-insensitive,
    matching death_date_from_uhc_fact's rule); the date comes from the Term
    Date column (index 28) — normalize_uhc() does not carry term_date through
    to MemberFact, so this script reads that column directly.
  - Humana August 2026 BOB:
    docs/Carrier BOB DL/Aug 2026 period/Humana/Active Policies (1).xlsx
    A row is a death when its Deceased Date column is populated.

Matching is EXACT UNIQUE-ID ONLY (see resolve_one): UHC rows by MedicareID
(Customer.mbi), Humana rows by Humana ID (Customer.humana_id). No name or DOB
fallback anywhere — an ID that doesn't resolve to exactly one customer is
reported and left untouched, never guessed at.

Expected result: about 20 customers marked — 15 from UHC (of 17-18 distinct
death MBIs across the UHC files read here, a few resolve to no customer and
are reported as refusals, not forced) and 5 from Humana. If a real run
produces a wildly different count, that is worth investigating before
--apply, not silently accepted.

Idempotent: apply_death()/set_carrier_value() never overwrite an existing
mark, so re-running (dry or --apply) after a successful apply reports 0 to
mark.

Usage:
    PYTHONPATH=. ./venv/bin/python3 scripts/backfill_deceased.py            # dry run
    PYTHONPATH=. ./venv/bin/python3 scripts/backfill_deceased.py --apply    # writes
"""
import argparse
import os
import sys

UHC_MAY = ("docs/Commission DL/_organized/2026-05_cycle/raw/UHC/"
           "statement-2813549-20260501 (4).xlsx")
UHC_JULY = ("docs/Commission DL/_organized/2026-07_cycle/"
            "Founders_Commission_July_2026/statement-2813549-20260701 (1).xlsx")
HUMANA_AUG = "docs/Carrier BOB DL/Aug 2026 period/Humana/Active Policies (1).xlsx"

_UHC_SHEET = "Commission Transactions"
_UHC_MEMBER = 7        # Member Name
_UHC_MBI = 8           # MedicareID
_UHC_TERMREASON = 24   # Term Reason — "Death" (case-insensitive) is the signal
_UHC_TERMDATE = 28     # Term Date


def resolve_one(agency_id, *, mbi=None, humana_id=None):
    """Return (customer, reason). EXACT unique-ID only — no name or DOB fallback.

    0 or >1 matches returns (None, reason): marking the wrong person deceased
    would erase a living customer from their agent's book, silently.
    """
    from app.models import Customer
    q = Customer.query.filter_by(agency_id=agency_id)
    if mbi:
        q = q.filter(Customer.mbi == mbi)
    elif humana_id:
        q = q.filter(Customer.humana_id == humana_id)
    else:
        return None, "no id supplied"
    rows = q.all()
    if len(rows) == 1:
        return rows[0], ""
    return None, ("no customer" if not rows else f"{len(rows)} customers share this id")


def _uhc_death_rows(path):
    """Yield (member_name, mbi, term_date) for every UHC 'Death' row in path."""
    import openpyxl
    from app.commission.payments import _parse_date

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[_UHC_SHEET]
    rows = ws.iter_rows(values_only=True)
    next(rows)  # header
    for row in rows:
        if not any(row) or len(row) <= _UHC_TERMDATE:
            continue
        reason = str(row[_UHC_TERMREASON] or "").strip()
        if reason.lower() != "death":
            continue
        mbi = str(row[_UHC_MBI] or "").strip()
        member = str(row[_UHC_MEMBER] or "").strip()
        when = _parse_date(row[_UHC_TERMDATE])
        if mbi and when:
            yield member, mbi, when


def _humana_death_rows(path):
    """Yield (member_name, humana_id, deceased_date) for every deceased row."""
    from app.parsers.humana import parse
    for rec in parse(path):
        if rec.get("deceased_date"):
            yield rec.get("full_name", ""), rec["member_id"], rec["deceased_date"]


def _money_totals():
    """(sum PolicyPayment.paid_amount, sum CommissionLineItem.raw_amount) across
    ALL agencies — the before/after invariant this script must never move."""
    from app.extensions import db
    from app.models import PolicyPayment, CommissionLineItem
    payments = db.session.query(db.func.coalesce(db.func.sum(PolicyPayment.paid_amount), 0.0)).scalar()
    ledger = db.session.query(db.func.coalesce(db.func.sum(CommissionLineItem.raw_amount), 0.0)).scalar()
    return round(float(payments or 0.0), 2), round(float(ledger or 0.0), 2)


def main(apply=False):
    from app import create_app
    from app.extensions import db
    from app.deceased import apply_death
    from app.models import Agency

    app = create_app()
    with app.app_context():
        for path in (UHC_MAY, UHC_JULY, HUMANA_AUG):
            if not os.path.exists(path):
                print(f"MISSING SOURCE FILE (skipping): {path}")

        agencies = Agency.query.all()
        if not agencies:
            print("No Agency row found — nothing to do.")
            return

        before_payments, before_ledger = _money_totals()

        marked = []
        refused = []
        seen_mbi = set()

        # Gather each source's death rows once, de-duping repeated MBI rows
        # within a single UHC file (a member can have several commission
        # lines the same month).
        uhc_rows = []
        if os.path.exists(UHC_MAY):
            for member, mbi, when in _uhc_death_rows(UHC_MAY):
                if mbi not in seen_mbi:
                    seen_mbi.add(mbi)
                    uhc_rows.append((member, mbi, when))
        if os.path.exists(UHC_JULY):
            for member, mbi, when in _uhc_death_rows(UHC_JULY):
                if mbi not in seen_mbi:
                    seen_mbi.add(mbi)
                    uhc_rows.append((member, mbi, when))

        humana_rows = list(_humana_death_rows(HUMANA_AUG)) if os.path.exists(HUMANA_AUG) else []

        # Resolve each row against every agency's Customer table (agency_id is
        # always non-nullable-in-practice scoping; resolve_one refuses cross-agency
        # ambiguity the same as intra-agency ambiguity). A single portal deployment
        # normally has one agency, but this must not assume that.
        for member, mbi, when in uhc_rows:
            customer = None
            reason = "no customer"
            for ag in agencies:
                got, why = resolve_one(ag.id, mbi=mbi)
                if got is not None:
                    customer = got
                    break
                reason = why
            if customer is None:
                refused.append(("UHC", member, mbi, reason))
                continue
            wrote = apply_death(customer, when, "uhc_commission_backfill",
                                customer.agency_id, carrier="UHC") if apply else \
                    (customer.deceased_date is None)
            marked.append(("UHC", member, mbi, customer.id, when, wrote))

        for member, humana_id, when in humana_rows:
            customer = None
            reason = "no customer"
            for ag in agencies:
                got, why = resolve_one(ag.id, humana_id=humana_id)
                if got is not None:
                    customer = got
                    break
                reason = why
            if customer is None:
                refused.append(("Humana", member, humana_id, reason))
                continue
            wrote = apply_death(customer, when, "humana_bob_backfill",
                                customer.agency_id, carrier="Humana") if apply else \
                    (customer.deceased_date is None)
            marked.append(("Humana", member, humana_id, customer.id, when, wrote))

        if apply:
            db.session.commit()

        after_payments, after_ledger = _money_totals()

        print(f"{'APPLY' if apply else 'DRY RUN'} — deceased backfill")
        print("-" * 60)
        print(f"{'carrier':8} {'member':28} {'id':14} {'customer_id':11} {'died':10} {'written'}")
        for carrier, member, cid, customer_id, when, wrote in marked:
            print(f"{carrier:8} {member:28} {cid:14} {customer_id:<11} {when} {wrote}")
        n_written = sum(1 for *_, wrote in marked if wrote)
        print(f"\n{len(marked)} row(s) resolved to a customer, {n_written} "
              f"{'written' if apply else 'would be written'}.")

        print(f"\nREFUSED ({len(refused)}) — no unique customer, left untouched:")
        for carrier, member, cid, reason in refused:
            print(f"  {carrier:8} {member:28} {cid:14} — {reason}")

        print(f"\nPolicyPayment total:      before {before_payments}  after {after_payments}"
              f"  {'OK' if before_payments == after_payments else 'MISMATCH!!'}")
        print(f"CommissionLineItem total: before {before_ledger}  after {after_ledger}"
              f"  {'OK' if before_ledger == after_ledger else 'MISMATCH!!'}")
        if before_payments != after_payments or before_ledger != after_ledger:
            print("\n*** MONEY TOTALS CHANGED — this must never happen. Investigate before trusting this run. ***")
            sys.exit(1)

        if not apply:
            print("\nDry run only — nothing written. Re-run with --apply to write.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write the marks. Default is dry-run (report only).")
    args = parser.parse_args()
    main(apply=args.apply)
