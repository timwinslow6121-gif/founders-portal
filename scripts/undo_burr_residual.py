"""
One-time follow-up to undo_mike_uhc_july_edits.py.

Two of Mike's July UHC rows (BURR JR, JIMMY V. -- lines 44515 / 44517) were
edited by AJ at 20:30 on 2026-08-01 like the other 36, but he then RE-SAVED
them at 20:32 with no actual change, stacking no-op revisions on top:

    line 44515: #132 4.85@0.525 -> 4.59@1.0 ,  #139 4.59@1.0 -> 4.59@1.0
    line 44517: #133 4.85@0.525 -> 4.59@1.0 ,  #140 + #141 no-ops

A single undo_last_change() only peels back the newest revision, so the first
pass skipped them (prior state looked identical to current). They need
repeated undos to reach the parsed values.

This walks undo_last_change() until the row matches the raw carrier file
(4.85 @ 0.525) or no un-undone revision remains. Dry-run by default.

    ./venv/bin/python3 scripts/undo_burr_residual.py            # dry run
    ./venv/bin/python3 scripts/undo_burr_residual.py --apply
"""
import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem, CommissionLineItemRevision, User
from app.commission.ledger import split_breakdown, undo_last_change

LINE_IDS = (44515, 44517)
TARGET_RAW = 4.85          # what the raw July UHC file shows for these members
TARGET_RATE = 0.525        # Mike's UHC contract
MAX_STEPS = 6              # safety stop; these have at most 3 revisions each


def _at_target(li):
    return (abs((li.raw_amount or 0) - TARGET_RAW) < 0.005
            and li.split_rate is not None
            and abs(li.split_rate - TARGET_RATE) < 0.0005)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        admin = User.query.filter_by(is_admin=True).first()
        print("Mode: %s" % ("APPLY" if args.apply else "DRY RUN"))
        print("Target: raw=%.2f rate=%s (raw file + Mike's contract)\n"
              % (TARGET_RAW, TARGET_RATE))

        pay_before = pay_after = keep_before = keep_after = 0.0

        for lid in LINE_IDS:
            li = CommissionLineItem.query.get(lid)
            if li is None:
                print("line %s: NOT FOUND" % lid)
                continue
            p0, k0 = split_breakdown(li)
            pay_before += p0
            keep_before += k0
            print("line %s (%s)" % (lid, li.member_name))
            print("   start : raw=%-7s rate=%-6s payout=%7.2f keep=%7.2f"
                  % (li.raw_amount, li.split_rate, p0, k0))

            if not args.apply:
                # count how many undos WOULD be needed, without writing
                pending = (CommissionLineItemRevision.query
                           .filter_by(line_item_id=lid, undone=False)
                           .filter(CommissionLineItemRevision.action != "undo")
                           .count())
                print("   %d un-undone revision(s) -> would undo until raw=%.2f/rate=%s"
                      % (pending, TARGET_RAW, TARGET_RATE))
                print()
                continue

            steps = 0
            while steps < MAX_STEPS and not _at_target(li):
                if not undo_last_change(li, user_id=admin.id if admin else None):
                    print("   no further revision to undo (stopped)")
                    break
                steps += 1
                print("   undo #%d -> raw=%-7s rate=%s"
                      % (steps, li.raw_amount, li.split_rate))

            p1, k1 = split_breakdown(li)
            pay_after += p1
            keep_after += k1
            ok = "OK" if _at_target(li) else "NOT AT TARGET"
            print("   end   : raw=%-7s rate=%-6s payout=%7.2f keep=%7.2f  [%s]"
                  % (li.raw_amount, li.split_rate, p1, k1, ok))
            print()

        if not args.apply:
            print("DRY RUN -- nothing written.")
            return 0

        db.session.commit()
        print("%-28s %10s %10s" % ("", "AGENT", "FOUNDERS"))
        print("%-28s %10.2f %10.2f" % ("before", pay_before, keep_before))
        print("%-28s %10.2f %10.2f" % ("after", pay_after, keep_after))
        print("%-28s %10.2f %10.2f" % ("change", pay_after - pay_before,
                                       keep_after - keep_before))
        return 0


if __name__ == "__main__":
    sys.exit(main())
