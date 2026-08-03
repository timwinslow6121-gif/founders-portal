"""
Backfill: split already-imported UHC PARTD **lumped** rows into their two real
components, at each agent's CONTRACTED rate.

UHC lumps a Part D renewal into ONE row containing both payments:

    $4.85 = $4.59 agent commission + $0.26 Founders override
    $4.43 = $4.17 agent commission + $0.26 Founders override

The agent half splits at the agent's contract rate; the $0.26 is 100% Founders.
Chargebacks mirror it, sign-preserved.

The PARSER now does this automatically (commit 17e3efc), so this script exists
only to correct rows imported BEFORE that landed. Re-importing those statements
is not an option -- `_ingest_normalized_upload` deletes ledger rows with no
`manually_adjusted` exclusion and would destroy AJ's manual work.

Splits via the existing `resolve_quarantine_line()` primitive, so the ::ovr
sibling, the revision/undo trail and the sum(raw) invariant all come from the
same code path the UI uses. Never deletes; never re-parses money.

    ./venv/bin/python3 scripts/split_uhc_partd_lumps.py            # dry run
    ./venv/bin/python3 scripts/split_uhc_partd_lumps.py --apply
    ./venv/bin/python3 scripts/split_uhc_partd_lumps.py --statement 80
"""
import argparse
import sys
from collections import defaultdict

from app import create_app
from app.extensions import db
from app.models import (CommissionLineItem, CommissionStatement, User,
                        AgentCarrierContract)
from app.commission.ledger import split_breakdown, resolve_quarantine_line

CARRIER = "UHC"
OVERRIDE = 0.26
# Keep in lockstep with app/commission/ledger.py::_UHC_PARTD_COMMISSIONS.
PARTD_COMMISSIONS = (4.59, 4.17)
LUMPS = tuple((c, round(c + OVERRIDE, 2)) for c in PARTD_COMMISSIONS)
CENT = 0.005


def _rate_for(agent_id, cache={}):
    if agent_id not in cache:
        c = (AgentCarrierContract.query
             .filter_by(agent_id=agent_id, carrier=CARRIER, is_active=True).first())
        cache[agent_id] = c.split_rate if c else None
    return cache[agent_id]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--statement", type=int, default=None,
                    help="limit to one statement id (default: all UHC)")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        users = {u.id: u.name for u in User.query.all()}
        admin = User.query.filter_by(is_admin=True).first()

        q = CommissionLineItem.query.filter(CommissionLineItem.carrier == CARRIER)
        if args.statement:
            q = q.filter(CommissionLineItem.statement_id == args.statement)

        targets, skipped = [], []
        for li in q.order_by(CommissionLineItem.statement_id,
                             CommissionLineItem.id).all():
            raw = round(li.raw_amount or 0.0, 2)
            base = next((b for b, lump in LUMPS if abs(abs(raw) - lump) < CENT), None)
            if base is None:
                continue
            if (li.source_ref or "").endswith("::ovr"):
                continue                      # never split an override sibling
            if li.agent_id is None:
                skipped.append((li, "no agent attributed"))
                continue
            rate = _rate_for(li.agent_id)
            if rate is None:
                skipped.append((li, "no active UHC contract"))
                continue
            targets.append((li, base, rate))

        print("Mode: %s%s" % ("APPLY" if args.apply else "DRY RUN",
                              ("  (statement %s only)" % args.statement)
                              if args.statement else ""))
        print("Lump shapes: %s" % ", ".join("%.2f=%.2f+%.2f" % (l, b, OVERRIDE)
                                            for b, l in LUMPS))
        print("Lumped rows found: %d   skipped: %d\n" % (len(targets), len(skipped)))

        if skipped:
            print("  SKIPPED (need a human):")
            for li, why in skipped:
                print("    line %-7s %-22s raw=%7.2f  %s"
                      % (li.id, (li.member_name or "")[:22], li.raw_amount or 0, why))
            print()

        if not targets:
            print("Nothing to split.")
            return 0

        print("  %-7s %-9s %-18s %-20s %8s | %8s %-6s %8s | %7s %8s"
              % ("line", "period", "agent", "member", "raw",
                 "new_raw", "rate", "agent", "ovr", "keep"))
        print("  " + "-" * 112)

        pb = kb = pa = ka = rb = ra = 0.0
        by_stmt = defaultdict(lambda: [0.0, 0.0])
        for li, base, rate in targets:
            st = CommissionStatement.query.get(li.statement_id)
            raw = round(li.raw_amount or 0.0, 2)
            sign = 1.0 if raw >= 0 else -1.0
            ov = round(sign * OVERRIDE, 2)
            comm = round(raw - ov, 2)

            p0, k0 = split_breakdown(li)
            new_pay = comm * rate
            new_keep = (comm - new_pay) + ov
            pb += p0; kb += k0; pa += new_pay; ka += new_keep
            rb += raw; ra += comm + ov
            by_stmt[li.statement_id][0] += raw
            by_stmt[li.statement_id][1] += comm + ov

            print("  %-7s %-9s %-18s %-20s %8.2f | %8.2f %-6s %8.2f | %7.2f %8.2f"
                  % (li.id, (st.period_label.split()[0] if st else "?"),
                     users.get(li.agent_id, "?")[:18],
                     (li.member_name or "")[:20], raw, comm, rate, new_pay,
                     ov, new_keep))

        print()
        print("  %-30s %10s %10s %12s" % ("", "AGENT", "FOUNDERS", "SUM RAW"))
        print("  %-30s %10.2f %10.2f %12.2f" % ("before (lumped)", pb, kb, rb))
        print("  %-30s %10.2f %10.2f %12.2f" % ("after (split)", pa, ka, ra))
        print("  %-30s %10.2f %10.2f %12.2f" % ("change", pa - pb, ka - kb, ra - rb))
        print()

        bad = [s for s, (b, a) in by_stmt.items() if abs(a - b) > CENT]
        if bad:
            print("  ABORT: sum(raw) would change on statement(s) %s. The split "
                  "must be value-preserving." % bad)
            return 1
        print("  sum(raw) preserved per statement -- value-neutral. OK.\n")

        if not args.apply:
            print("DRY RUN -- nothing written. Re-run with --apply to split %d rows."
                  % len(targets))
            return 0

        for li, base, rate in targets:
            sign = 1.0 if (li.raw_amount or 0) >= 0 else -1.0
            resolve_quarantine_line(li, li.agent_id, round(sign * OVERRIDE, 2), rate,
                                    user_id=admin.id if admin else None)
        db.session.commit()
        print("APPLIED: split %d rows." % len(targets))

        left = sum(1 for li in q.all()
                   if any(abs(abs(li.raw_amount or 0) - l) < CENT for _, l in LUMPS)
                   and not (li.source_ref or "").endswith("::ovr"))
        print("Lumped rows remaining: %d" % left)
        return 0


if __name__ == "__main__":
    sys.exit(main())
