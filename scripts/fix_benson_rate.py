"""
One-time: restore the contract rate on Rebekah's BENSON, JANA July UHC renewal.

AJ resolved this row correctly at Rebekah's 0.55 on 08-01, then re-edited it on
08-03 00:45 (the same batch as the SEID rows) and the edit form overwrote
split_rate with 1.0 -- so Rebekah receives the whole $25.21 and Founders keeps
$0, contradicting her contract.

    #94   resolve  08-01 17:49   28.56@None  -> 28.56@0.55   (correct)
    #260  edit     08-03 00:45   28.56@0.55  -> 25.21@1.0    (rate clobbered)

Scoped to this ONE line deliberately. A broader sweep found 17 rows at 1.0 that
were previously at a contract rate, but 13 are Anjana Patel's, whose 100% share
on non-Cannon-Pharmacy customers is CORRECT BY DESIGN and set by AJ on purpose
(Tim, 2026-08-01). Two more are $0.00 rows (cosmetic). Only this row is a
genuine loss of a correct rate.

Fixes the RATE only. raw_amount ($25.21), classification and the $3.35 ::ovr
sibling are AJ's and stay untouched.

    ./venv/bin/python3 scripts/fix_benson_rate.py            # dry run
    ./venv/bin/python3 scripts/fix_benson_rate.py --apply
"""
import argparse
import json
import sys

from app import create_app
from app.extensions import db
from app.models import (CommissionLineItem, CommissionLineItemRevision, User,
                        AgentCarrierContract)
from app.commission.ledger import split_breakdown, _snapshot_line

LINE_ID = 44701
EXPECT_MEMBER = "BENSON"
EXPECT_CARRIER = "UHC"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        li = CommissionLineItem.query.get(LINE_ID)
        if li is None:
            print("line %s not found" % LINE_ID)
            return 1
        # Guard: make sure we are editing the row we think we are.
        if EXPECT_MEMBER not in (li.member_name or "").upper() \
                or li.carrier != EXPECT_CARRIER:
            print("line %s is %r on %s -- not the expected BENSON/UHC row. Aborting."
                  % (LINE_ID, li.member_name, li.carrier))
            return 1
        if li.split_rate is None or abs(li.split_rate - 1.0) > 0.0005:
            print("line %s is already at rate %s -- nothing to do."
                  % (LINE_ID, li.split_rate))
            return 0

        contract = (AgentCarrierContract.query
                    .filter_by(agent_id=li.agent_id, carrier=EXPECT_CARRIER,
                               is_active=True).first())
        if contract is None:
            print("no active %s contract for agent %s -- refusing to guess."
                  % (EXPECT_CARRIER, li.agent_id))
            return 1
        rate = contract.split_rate

        agent = User.query.get(li.agent_id)
        p0, k0 = split_breakdown(li)
        new_pay = (li.raw_amount or 0) * rate
        new_keep = (li.raw_amount or 0) - new_pay

        sib = CommissionLineItem.query.filter_by(
            statement_id=li.statement_id,
            source_ref="%s::ovr" % li.source_ref).first()

        print("Mode: %s\n" % ("APPLY" if args.apply else "DRY RUN"))
        print("  line     : %s  (%s)" % (li.id, li.source_ref))
        print("  member   : %s" % li.member_name)
        print("  agent    : %s (contract %s @ %s)"
              % (agent.name if agent else li.agent_id, EXPECT_CARRIER, rate))
        print("  raw      : %.2f   (unchanged)" % (li.raw_amount or 0))
        print("  sibling  : %s" % ("%.2f override (unchanged)" % sib.raw_amount
                                   if sib else "none"))
        print()
        print("  %-22s %10s %10s" % ("", "AGENT", "FOUNDERS"))
        print("  %-22s %10.2f %10.2f" % ("now (rate 1.0)", p0, k0))
        print("  %-22s %10.2f %10.2f" % ("corrected (rate %s)" % rate, new_pay, new_keep))
        print("  %-22s %10.2f %10.2f" % ("change", new_pay - p0, new_keep - k0))
        print()

        if not args.apply:
            print("DRY RUN -- nothing written.")
            return 0

        admin = User.query.filter_by(is_admin=True).first()
        before = _snapshot_line(li)
        li.split_rate = rate
        db.session.add(CommissionLineItemRevision(
            agency_id=li.agency_id, line_item_id=li.id,
            statement_id=li.statement_id, action="edit",
            user_id=admin.id if admin else None,
            before_json=json.dumps(before),
            after_json=json.dumps(_snapshot_line(li))))
        db.session.commit()
        p1, k1 = split_breakdown(li)
        print("APPLIED: rate %s -> %s. Agent %.2f / Founders %.2f."
              % (1.0, rate, p1, k1))
        return 0


if __name__ == "__main__":
    sys.exit(main())
