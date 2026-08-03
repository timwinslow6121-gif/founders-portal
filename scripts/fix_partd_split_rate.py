"""
Correct the split_rate on hand-split UHC PARTD commission rows.

AJ splits the lumped $4.85 PARTD row by hand every month (the parser does not
yet decompose it -- see docs/superpowers/specs/2026-08-01-uhc-partd-lumped-rows-design.md).
He does the SPLIT correctly, producing a $4.59 commission row plus a $0.26
Founders override sibling. His only error is setting split_rate=1.0 on the
commission half, so the agent receives 100% of it and Founders keeps nothing --
contradicting the agent's contract.

This fixes ONLY the rate. It does not touch raw_amount, classification, the
::ovr siblings, or any row whose structure is already correct.

Targets rows that are ALL of:
  - carrier UHC, classification agent_commission or chargeback
  - abs(raw_amount) == 4.59 (the PARTD commission half; 4.17 also supported)
  - split_rate == 1.0
  - has a $0.26 ::ovr sibling  (proves it is a hand-split PARTD lump, not
    Anjana's legitimate non-Cannon 100% arrangement)

That last condition is the safety gate: Anjana's rate=1.0 rows are correct by
design and have no 0.26 sibling, so they can never be caught here.

    ./venv/bin/python3 scripts/fix_partd_split_rate.py            # dry run
    ./venv/bin/python3 scripts/fix_partd_split_rate.py --apply
"""
import argparse
import json
import sys

from app import create_app
from app.extensions import db
from app.models import (CommissionLineItem, CommissionLineItemRevision,
                        CommissionStatement, User, AgentCarrierContract)
from app.commission.ledger import split_breakdown, _snapshot_line

CARRIER = "UHC"
COMMISSION_HALVES = (4.59, 4.17)   # PARTD commission amounts that pair with 0.26
OVERRIDE = 0.26
CENT = 0.005


def _contract_rate(agent_id):
    c = (AgentCarrierContract.query
         .filter_by(agent_id=agent_id, carrier=CARRIER, is_active=True).first())
    return c.split_rate if c else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        users = {u.id: u.name for u in User.query.all()}
        admin = User.query.filter_by(is_admin=True).first()

        candidates = (CommissionLineItem.query
                      .filter(CommissionLineItem.carrier == CARRIER,
                              CommissionLineItem.split_rate == 1.0,
                              CommissionLineItem.agent_id.isnot(None))
                      .order_by(CommissionLineItem.statement_id,
                                CommissionLineItem.id).all())

        targets = []
        for li in candidates:
            if not any(abs(abs(li.raw_amount or 0) - h) < CENT
                       for h in COMMISSION_HALVES):
                continue
            # Safety gate: must have a 0.26 override sibling.
            sib = CommissionLineItem.query.filter_by(
                statement_id=li.statement_id,
                source_ref="%s::ovr" % li.source_ref).first()
            if sib is None or abs(abs(sib.raw_amount or 0) - OVERRIDE) > CENT:
                continue
            rate = _contract_rate(li.agent_id)
            if rate is None or abs(rate - 1.0) < 0.0005:
                continue          # no contract, or genuinely a 100% agent
            targets.append((li, rate))

        print("Mode: %s" % ("APPLY" if args.apply else "DRY RUN"))
        print("Rows with rate=1.0 on a PARTD commission half + a 0.26 sibling: %d\n"
              % len(targets))
        if not targets:
            print("Nothing to do.")
            return 0

        print("  %-7s %-9s %-20s %-20s %7s %7s | %8s %8s | %8s %8s"
              % ("line", "period", "agent", "member", "raw", "->rate",
                 "pay_now", "keep_now", "pay_new", "keep_new"))
        print("  " + "-" * 118)

        pb = kb = pa = ka = 0.0
        for li, rate in targets:
            st = CommissionStatement.query.get(li.statement_id)
            p0, k0 = split_breakdown(li)
            new_pay = (li.raw_amount or 0) * rate
            new_keep = (li.raw_amount or 0) - new_pay
            pb += p0; kb += k0; pa += new_pay; ka += new_keep
            print("  %-7s %-9s %-20s %-20s %7.2f %7s | %8.2f %8.2f | %8.2f %8.2f"
                  % (li.id, (st.period_label.split()[0] if st else "?"),
                     users.get(li.agent_id, "?")[:20],
                     (li.member_name or "")[:20], li.raw_amount or 0, rate,
                     p0, k0, new_pay, new_keep))

        print()
        print("  %-30s %10s %10s" % ("", "AGENT", "FOUNDERS"))
        print("  %-30s %10.2f %10.2f" % ("current (rate 1.0)", pb, kb))
        print("  %-30s %10.2f %10.2f" % ("corrected (contract rate)", pa, ka))
        print("  %-30s %10.2f %10.2f" % ("change", pa - pb, ka - kb))
        print()

        if not args.apply:
            print("DRY RUN -- nothing written. Re-run with --apply to fix %d rows."
                  % len(targets))
            return 0

        for li, rate in targets:
            before = _snapshot_line(li)
            li.split_rate = rate
            db.session.add(CommissionLineItemRevision(
                agency_id=li.agency_id, line_item_id=li.id,
                statement_id=li.statement_id, action="edit",
                user_id=admin.id if admin else None,
                before_json=json.dumps(before),
                after_json=json.dumps(_snapshot_line(li))))
        db.session.commit()
        print("APPLIED: corrected split_rate on %d rows." % len(targets))
        return 0


if __name__ == "__main__":
    sys.exit(main())
