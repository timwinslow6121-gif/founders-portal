"""Cross-carrier switcher pass — term the STALE UHC policy for 2 confirmed
Devoted switchers (same MBI on both carriers, Devoted eff newer = current).
Dry-run default; --apply.

Confirmed by name+dob+ADDRESS + same-MBI-on-both (2026-07-24):
  Timothy Elliott (cust 5765, mbi 2E02PQ5UT83): UHC eff 2025-01-01 -> Devoted eff 2026-07-01
  Mary Coe        (cust 5979, mbi 2TD4ET9HN61): UHC eff 2026-05-01 -> Devoted eff 2026-07-01

NOT included: John Connelly (UHC Medigap + Humana PDP = legitimate COEXISTENCE,
not a switch — leave both active).

SAFETY per row: verify the UHC policy belongs to the expected customer+MBI, is
'active', and that the SAME customer holds an active Devoted policy with the SAME
MBI and a NEWER effective date, before terming. Sets term_date = Devoted eff - 1
day (Medicare month-end convention) + status='termed' + term_reason.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/term_devoted_switchers.py [--apply]
"""
import sys
from datetime import timedelta
from app import create_app
from app.extensions import db
from app.models import Policy, Customer

# (customer_id, mbi, uhc_policy_id)
TARGETS = [
    (5765, "2E02PQ5UT83", None),   # Timothy Elliott
    (5979, "2TD4ET9HN61", None),   # Mary Coe
]


def main(apply):
    app = create_app()
    with app.app_context():
        print("%s — term stale UHC for 2 Devoted switchers\n" % ("APPLY" if apply else "DRY-RUN"))
        termed = 0
        for cid, mbi, _ in TARGETS:
            c = db.session.get(Customer, cid)
            if not c or (c.mbi or "").upper() != mbi:
                print("  ! cust %s mbi mismatch (%r != %s) — SKIP" % (cid, (c.mbi if c else None), mbi))
                continue
            pols = Policy.query.filter_by(customer_id=cid).all()
            uhc = [p for p in pols if p.carrier == "UHC" and p.status == "active"]
            dev = [p for p in pols if p.carrier == "Devoted" and p.status == "active"]
            if len(uhc) != 1 or not dev:
                print("  ! cust %s (%s): expected 1 active UHC + >=1 active Devoted, got UHC=%d Dev=%d — SKIP"
                      % (cid, c.full_name, len(uhc), len(dev)))
                continue
            up = uhc[0]
            dp = max(dev, key=lambda p: p.effective_date or "")
            # SAFETY: same MBI keyed on both + Devoted NEWER
            if up.member_id != mbi or dp.member_id != mbi:
                print("  ! cust %s: member_id not the MBI on both (UHC=%r Dev=%r) — SKIP"
                      % (cid, up.member_id, dp.member_id))
                continue
            if not (dp.effective_date and up.effective_date and dp.effective_date > up.effective_date):
                print("  ! cust %s: Devoted eff not newer than UHC (UHC=%s Dev=%s) — SKIP"
                      % (cid, up.effective_date, dp.effective_date))
                continue
            close = dp.effective_date - timedelta(days=1)
            print("  term UHC pol %s %-18s eff=%s  -> termed @ %s (switched to Devoted eff %s)"
                  % (up.id, c.full_name, up.effective_date, close, dp.effective_date))
            # Close the OPEN UHC AOR chapter at the term date too — terming the
            # policy without this leaves a stale open interval so the timeline shows
            # UHC as still-current alongside the active Devoted (Tim caught this).
            from app.models import CustomerAorHistory
            open_iv = CustomerAorHistory.query.filter_by(
                customer_id=cid, carrier="UHC", end_date=None).first()
            aor_note = " + close AOR" if open_iv else " (no open AOR)"
            print("     %s" % aor_note.strip())
            if apply:
                up.status = "termed"
                up.term_date = close
                up.term_reason = "Switched to Devoted"   # <=32 chars (term_reason col)
                up.new_carrier = "Devoted"
                if open_iv:
                    open_iv.end_date = close
                termed += 1
        if apply:
            db.session.commit()
            print("\nAPPLIED — %d UHC policies termed." % termed)
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
