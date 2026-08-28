"""Review report: customers holding the SAME plan twice, both policies active.

Tim spotted this on the customer list (Rebecca Howell, Tony Howell, Johnny
Johnson) — the primary-medical plan and the "other active plan" are the same
plan. It is the THIRD instance of one bug, after BCBS and Devoted:

  a carrier's BOB keys a member one way, its commission file keys the same
  member another way, and NEITHER row carries an MBI to bridge them, so
  _upsert_customer_from_policy's (carrier, member_id) -> (carrier, mbi)
  dedup can't match and a second policy is created for one enrollment.

    Humana : legacy commission id '673316570'  vs  BOB policy no 'H78438403'
    Devoted: MBI-shaped id                     vs  'D…' member locator

READ-ONLY. Writes a CSV for human review; merges nothing. The merge rule is
NOT obvious from the data alone (see the PAYMENTS columns) — decide first,
then run the merge script.

Run: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
       scripts/report_duplicate_coverage_pairs.py [--out PATH]
"""
import csv
import re
import sys

from app import create_app
from app.extensions import db
from app.models import Customer, Plan, Policy, PolicyPayment

AGENCY_ID = 1


def _shape(member_id):
    """Which identifier namespace does this member_id belong to?"""
    if not member_id:
        return "none"
    if re.fullmatch(r"H\d+", member_id):
        return "humana-bob"
    if re.fullmatch(r"\d+", member_id):
        return "numeric-legacy"
    if re.fullmatch(r"[0-9A-Z]{11}", member_id):
        return "mbi-shaped"
    return "other"


def _pay_summary(policy_id):
    q = PolicyPayment.query.filter_by(policy_id=policy_id)
    n = q.count()
    if not n:
        return 0, "", ""
    dates = [p.statement_date for p in q if p.statement_date]
    return n, (min(dates).isoformat() if dates else ""), (max(dates).isoformat() if dates else "")


def main(out_path):
    app = create_app()
    with app.app_context():
        p1, p2 = db.aliased(Policy), db.aliased(Policy)
        pairs = (db.session.query(p1, p2)
                 .join(p2, db.and_(p1.customer_id == p2.customer_id,
                                   p1.plan_id == p2.plan_id,
                                   p1.id < p2.id))
                 .filter(p1.agency_id == AGENCY_ID, p2.agency_id == AGENCY_ID,
                         p1.status == "active", p2.status == "active",
                         p1.plan_id.isnot(None), p1.customer_id.isnot(None))
                 .all())

        rows = []
        for a, b in pairs:
            cust = Customer.query.get(a.customer_id)
            plan = Plan.query.get(a.plan_id)
            a_pays, a_first, a_last = _pay_summary(a.id)
            b_pays, b_first, b_last = _pay_summary(b.id)

            # Which side do commission files actually pay against? That is the
            # side whose member_id must survive, or payments stop matching.
            if a_pays and not b_pays:
                paid_side = "A only"
            elif b_pays and not a_pays:
                paid_side = "B only"
            elif a_pays and b_pays:
                paid_side = "BOTH — needs a human"
            else:
                paid_side = "neither"

            rows.append({
                "customer_id": cust.id,
                "customer": cust.full_name,
                "dob": cust.dob.isoformat() if cust.dob else "",
                "carrier": a.carrier,
                "plan": plan.plan_name if plan else "",
                "cms_id": (plan.cms_plan_id if plan else "") or "",
                "same_effective_date": a.effective_date == b.effective_date,
                "A_policy_id": a.id, "A_member_id": a.member_id or "",
                "A_id_shape": _shape(a.member_id),
                "A_effective": a.effective_date.isoformat() if a.effective_date else "",
                "A_payments": a_pays, "A_first_pay": a_first, "A_last_pay": a_last,
                "B_policy_id": b.id, "B_member_id": b.member_id or "",
                "B_id_shape": _shape(b.member_id),
                "B_effective": b.effective_date.isoformat() if b.effective_date else "",
                "B_payments": b_pays, "B_first_pay": b_first, "B_last_pay": b_last,
                "paid_side": paid_side,
            })

        rows.sort(key=lambda r: (r["carrier"], r["customer"]))
        with open(out_path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

        by_carrier, by_paid, same_eff = {}, {}, 0
        for r in rows:
            by_carrier[r["carrier"]] = by_carrier.get(r["carrier"], 0) + 1
            by_paid[r["paid_side"]] = by_paid.get(r["paid_side"], 0) + 1
            same_eff += bool(r["same_effective_date"])

        print(f"duplicate-coverage pairs (same plan, both active): {len(rows)}")
        for k, v in sorted(by_carrier.items(), key=lambda kv: -kv[1]):
            print(f"   {k:10s} {v}")
        print(f"\nsame effective date on both rows: {same_eff}   differing: {len(rows)-same_eff}")
        print("\nwhich side carries commission payments:")
        for k, v in sorted(by_paid.items(), key=lambda kv: -kv[1]):
            print(f"   {k:22s} {v}")
        print(f"\nwrote {out_path}")


if __name__ == "__main__":
    out = "/tmp/duplicate_coverage_pairs.csv"
    if "--out" in sys.argv:
        out = sys.argv[sys.argv.index("--out") + 1]
    main(out)
