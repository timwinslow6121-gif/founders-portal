"""
Split Mike Lauzurique's lumped $4.85 UHC PARTD rows into their two real
components, at his CONTRACTED rate.

BACKGROUND (Tim, 2026-08-01)
UHC lumps two payments into one $4.85 PARTD row:

    $4.85  =  $4.59 agent commission  +  $0.26 Founders override

The $4.59 splits at the agent's contract rate; the $0.26 is 100% Founders
(the documented "$0.26 PARTD renewal -> Founders override" case).

AJ hand-edited these rows on 2026-08-01 to perform exactly this split, and he
was RIGHT to do so -- but he set split_rate=1.0 on the $4.59 part, so Mike
received the whole $4.59 instead of his 52.5%. An earlier undo pass reverted
the edits wholesale, which also deleted the $0.26 override siblings the edits
had created. This script restores the intended structure with the correct rate.

Correct end state per $4.85 row:
    parent  raw=  4.59  split_rate=0.525  agent_commission   -> Mike $2.41 / Founders $2.18
    sibling raw=  0.26  split_rate=None   founders_override  -> Founders $0.26

Chargebacks mirror it (Tim's call, 2026-08-01):
    parent  raw= -4.59  split_rate=0.525  chargeback         -> Mike -$2.41 / Founders -$2.18
    sibling raw= -0.26  split_rate=None   founders_override  -> Founders -$0.26

Uses the EXISTING resolve_quarantine_line() primitive so the sibling is created,
the revision/undo trail is written, and sum(raw) is preserved by construction
(commission_part + override == original raw).

    ./venv/bin/python3 scripts/split_uhc_lumped_485.py            # dry run
    ./venv/bin/python3 scripts/split_uhc_lumped_485.py --apply
"""
import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem, User, AgentCarrierContract
from app.commission.ledger import split_breakdown, resolve_quarantine_line

STATEMENT_ID = 80        # UHC July 2026
CARRIER = "UHC"
LUMP = 4.85              # the lumped PARTD amount
OVERRIDE = 0.26          # Founders' share of the lump
MEMBER_KEYS = ("GRIFFIN, ROGER", "BURR JR", "LEISENRING")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agent", default="lauzurique")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        agent = User.query.filter(User.name.ilike("%%%s%%" % args.agent)).first()
        contract = (AgentCarrierContract.query
                    .filter_by(agent_id=agent.id, carrier=CARRIER, is_active=True)
                    .first())
        rate = contract.split_rate if contract else None
        if rate is None:
            print("No active %s contract for %s -- refusing to guess a rate."
                  % (CARRIER, agent.name))
            return 1

        # Only rows still at the lumped amount, i.e. not already split.
        rows = [r for r in CommissionLineItem.query
                .filter_by(statement_id=STATEMENT_ID, agent_id=agent.id)
                .order_by(CommissionLineItem.id).all()
                if abs(abs(r.raw_amount or 0) - LUMP) < 0.005
                and any(k in (r.member_name or "").upper() for k in MEMBER_KEYS)
                and not (r.source_ref or "").endswith("::ovr")]

        print("Agent    : %s (id=%s)   %s contract rate = %s"
              % (agent.name, agent.id, CARRIER, rate))
        print("Statement: %s" % STATEMENT_ID)
        print("Lumped rows found: %d   (%.2f -> %.2f @ %s  +  %.2f Founders)"
              % (len(rows), LUMP, LUMP - OVERRIDE, rate, OVERRIDE))
        print("Mode     : %s\n" % ("APPLY" if args.apply else "DRY RUN"))
        if not rows:
            print("Nothing to do.")
            return 0

        print("  %-7s %-22s %9s | %9s %-6s %8s | %8s %8s"
              % ("line", "member", "raw", "new_raw", "rate", "agent", "ovr", "keep"))
        print("  " + "-" * 86)

        pay_b = keep_b = pay_a = keep_a = 0.0
        raw_b = raw_a = 0.0
        planned = []

        for li in rows:
            raw = round(li.raw_amount or 0.0, 2)
            # override carries the SAME SIGN as the row (chargebacks mirror)
            ov = OVERRIDE if raw > 0 else -OVERRIDE
            commission_part = round(raw - ov, 2)

            p0, k0 = split_breakdown(li)
            pay_b += p0; keep_b += k0; raw_b += raw

            # projected post-split money
            new_pay = commission_part * rate
            new_keep = (commission_part - new_pay) + ov
            pay_a += new_pay; keep_a += new_keep; raw_a += commission_part + ov

            print("  %-7s %-22s %9.2f | %9.2f %-6s %8.2f | %8.2f %8.2f"
                  % (li.id, (li.member_name or "")[:22], raw,
                     commission_part, rate, new_pay, ov, new_keep))
            planned.append((li, ov))

        print()
        print("  %-30s %10s %10s %12s" % ("", "AGENT", "FOUNDERS", "SUM RAW"))
        print("  %-30s %10.2f %10.2f %12.2f" % ("before (lumped @ rate)", pay_b, keep_b, raw_b))
        print("  %-30s %10.2f %10.2f %12.2f" % ("after (split correctly)", pay_a, keep_a, raw_a))
        print("  %-30s %10.2f %10.2f %12.2f" % ("change", pay_a - pay_b, keep_a - keep_b, raw_a - raw_b))
        print()
        if abs(raw_a - raw_b) > 0.005:
            print("  ABORT: sum(raw) would change (%.2f -> %.2f). The split must be "
                  "value-preserving." % (raw_b, raw_a))
            return 1
        print("  sum(raw) preserved -- the split is value-neutral. OK.")
        print()

        if not args.apply:
            print("DRY RUN -- nothing written. Re-run with --apply to split %d rows."
                  % len(planned))
            return 0

        admin = User.query.filter_by(is_admin=True).first()
        n = 0
        for li, ov in planned:
            resolve_quarantine_line(li, agent.id, ov, rate,
                                    user_id=admin.id if admin else None)
            n += 1
        db.session.commit()
        print("APPLIED: split %d rows." % n)
        return 0


if __name__ == "__main__":
    sys.exit(main())
