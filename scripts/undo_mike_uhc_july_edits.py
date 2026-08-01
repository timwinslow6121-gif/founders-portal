"""
One-time: review / undo AJ's 2026-08-01 inline edits to Mike Lauzurique's
July-2026 UHC PARTD rows.

BACKGROUND
AJ hand-edited 38 of Mike's July UHC line items between 20:30 and 20:47 on
2026-08-01, changing BOTH the amount and the split rate:

    BEFORE  raw=4.85  split_rate=0.525   (parser; matches the raw file)
    AFTER   raw=4.59  split_rate=1.0     (AJ's edit)

The raw carrier file (statement-2813549-20260701 (1).xlsx) shows these three
members as $4.85 PARTD ONLY -- 21 payments at +4.85 and 18 chargebacks at
-4.85, with no 4.59 rows at all. May and June statements show the same members
at 4.85 @ 0.525. So the parsed values matched source truth and the edits moved
away from it.

split_rate=1.0 is the inline-edit convention for "a human typed these exact
dollars, do not recompute" -- so the effect is that Mike receives 100% of each
row and Founders keeps nothing, contradicting his 52.5% contract.

WHAT THIS DOES
Dry-run by default: prints every affected row's before/after and the money
delta, and changes nothing. With --apply it calls the EXISTING
undo_last_change() primitive per line, which restores the exact prior state
from the revision's before_json and reverses any ::ovr sibling. It does not
hand-write field values.

USAGE
    ./venv/bin/python3 scripts/undo_mike_uhc_july_edits.py            # dry run
    ./venv/bin/python3 scripts/undo_mike_uhc_july_edits.py --apply
"""
import argparse
import json
import sys

from app import create_app
from app.extensions import db
from app.models import (CommissionLineItem, CommissionLineItemRevision, User,
                        AgentCarrierContract)
from app.commission.ledger import split_breakdown, undo_last_change

STATEMENT_ID = 80          # UHC July 2026
CARRIER = "UHC"


def _contract_rate(agent_id, agency_id):
    c = (AgentCarrierContract.query
         .filter_by(agent_id=agent_id, carrier=CARRIER, is_active=True)
         .first())
    return c.split_rate if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually undo (default is dry-run)")
    ap.add_argument("--agent", default="lauzurique",
                    help="substring of the agent name (default: lauzurique)")
    ap.add_argument("--skip-noop", action="store_true",
                    help="skip rows whose prior state is identical to the current "
                         "one (edited in an EARLIER session, so a one-step undo "
                         "would restore them to the same wrong values)")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        agent = User.query.filter(User.name.ilike("%%%s%%" % args.agent)).first()
        if agent is None:
            print("No agent matching %r" % args.agent)
            return 1

        rows = (CommissionLineItem.query
                .filter_by(statement_id=STATEMENT_ID, agent_id=agent.id,
                           manually_adjusted=True)
                .order_by(CommissionLineItem.id).all())

        rate = _contract_rate(agent.id, agent.agency_id)
        print("Agent      : %s (id=%s)" % (agent.name, agent.id))
        print("Contract   : %s @ %s" % (CARRIER, rate))
        print("Statement  : %s (UHC July 2026)" % STATEMENT_ID)
        print("Edited rows: %d" % len(rows))
        print("Mode       : %s" % ("APPLY" if args.apply else "DRY RUN"))
        print()

        if not rows:
            print("Nothing to do.")
            return 0

        hdr = ("  %-7s %-22s | %-9s %-6s %-9s | %-9s %-6s %-9s | %s" %
               ("line", "member", "now_raw", "rate", "now_pay",
                "was_raw", "rate", "was_pay", "delta"))
        print(hdr)
        print("  " + "-" * (len(hdr) - 2))

        now_total = was_total = 0.0
        keep_now = keep_was = 0.0
        planned = []
        skipped = []

        for li in rows:
            rev = (CommissionLineItemRevision.query
                   .filter_by(line_item_id=li.id, undone=False)
                   .filter(CommissionLineItemRevision.action != "undo")
                   .order_by(CommissionLineItemRevision.id.desc())
                   .first())
            if rev is None:
                print("  %-7s %-22s | NO REVISION -- cannot undo, skipping" %
                      (li.id, (li.member_name or "")[:22]))
                continue

            before = json.loads(rev.before_json or "{}")
            now_pay, now_keep = split_breakdown(li)

            class _Shim:
                pass
            shim = _Shim()
            shim.raw_amount = before.get("raw_amount")
            shim.split_rate = before.get("split_rate")
            shim.classification = before.get("classification")
            was_pay, was_keep = split_breakdown(shim)

            # A no-op means this row's PRIOR state is the same as its current one,
            # i.e. it was edited in an earlier session too. One-step undo would
            # restore it to the same wrong values, so --skip-noop leaves it alone
            # for separate investigation rather than pretending it was fixed.
            noop = (abs((shim.raw_amount or 0) - (li.raw_amount or 0)) < 0.005
                    and shim.split_rate == li.split_rate)
            if noop and args.skip_noop:
                print("  %-7s %-22s | %9.2f %-6s %9.2f | SKIPPED (prior state identical"
                      " -- edited before tonight)" %
                      (li.id, (li.member_name or "")[:22],
                       li.raw_amount or 0, li.split_rate, now_pay))
                skipped.append(li)
                continue

            now_total += now_pay
            was_total += was_pay
            keep_now += now_keep
            keep_was += was_keep

            print("  %-7s %-22s | %9.2f %-6s %9.2f | %9.2f %-6s %9.2f | %+8.2f%s" %
                  (li.id, (li.member_name or "")[:22],
                   li.raw_amount or 0, li.split_rate, now_pay,
                   shim.raw_amount or 0, shim.split_rate, was_pay,
                   was_pay - now_pay, "  <== no-op" if noop else ""))
            planned.append(li)

        print()
        print("  %-34s %12s %12s" % ("", "AGENT", "FOUNDERS"))
        print("  %-34s %12.2f %12.2f" % ("current (after AJ's edits)", now_total, keep_now))
        print("  %-34s %12.2f %12.2f" % ("restored (parser values)", was_total, keep_was))
        print("  %-34s %12.2f %12.2f" % ("change", was_total - now_total, keep_was - keep_now))
        if skipped:
            print()
            print("  SKIPPED %d row(s) whose prior state was already wrong "
                  "(edited before tonight):" % len(skipped))
            for li in skipped:
                print("    line %-7s %-22s raw=%.2f rate=%s" %
                      (li.id, (li.member_name or "")[:22], li.raw_amount or 0,
                       li.split_rate))
            print("  These need separate investigation -- a one-step undo cannot fix them.")
        print()

        if not args.apply:
            print("DRY RUN -- nothing written. Re-run with --apply to undo %d rows."
                  % len(planned))
            return 0

        admin = User.query.filter_by(is_admin=True).first()
        undone = 0
        for li in planned:
            if undo_last_change(li, user_id=admin.id if admin else None):
                undone += 1
        db.session.commit()
        print("APPLIED: undid %d of %d rows." % (undone, len(planned)))

        # verify
        still = (CommissionLineItem.query
                 .filter_by(statement_id=STATEMENT_ID, agent_id=agent.id,
                            manually_adjusted=True).count())
        print("Rows still flagged manually_adjusted for this agent: %d" % still)
        return 0


if __name__ == "__main__":
    sys.exit(main())
