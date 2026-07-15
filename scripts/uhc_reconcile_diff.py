"""UHC BOB <-> DB reconciliation — READ-ONLY diff + categorize (no writes).

Mirrors the Aetna reconciliation method (2026-07-10 handoff):
  - BOB active = policyTermDate sentinel 2300-01-01 (2189 rows / 2188 people).
  - Match a DB active UHC policy to a BOB row by memberNumber OR mbiNumber, BOTH
    formats (MBIs change; member_id is more stable). CROSS-carrier switchers are a
    later pass — this script only reports the UHC-internal diff.

Run on the VPS (DB is local there):
  FLASK_APP=wsgi.py PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
    scripts/uhc_reconcile_diff.py "docs/Carrier BOB DL/July 2026 period/UHC/UHC book of business.xlsx"

Outputs counts + writes a categorized CSV to scripts/uhc_reconcile_report.csv.
NOTHING is modified.
"""
import sys
import csv
import pandas as pd

from app import create_app
from app.extensions import db
from app.models import Policy, Customer, User

BOB_ACTIVE_SENTINEL = "2300-01-01"


def _norm(s):
    return (str(s).strip().upper() if s is not None and str(s) != "nan" else "")


def load_bob(path):
    df = pd.read_excel(path, header=2, dtype=str).dropna(how="all")
    active = df[df["policyTermDate"] == BOB_ACTIVE_SENTINEL].copy()
    pending = df[df["policyTermDate"] == "2026-07-31"].copy()
    # index BOB active by MBI and by memberNumber for O(1) matching
    by_mbi, by_member = {}, {}
    rows = []
    for _, r in active.iterrows():
        rec = {
            "first": _norm(r.get("memberFirstName")),
            "last": _norm(r.get("memberLastName")),
            "dob": _norm(r.get("dateOfBirth")),
            "mbi": _norm(r.get("mbiNumber")),
            "member_number": _norm(r.get("memberNumber")),
            "contract": _norm(r.get("contract")),
            "pbp": _norm(r.get("pbp")),
            "plan": f"{_norm(r.get('contract'))}-{_norm(r.get('pbp'))}",
            "eff": _norm(r.get("policyEffectiveDate")),
            "agent_id": _norm(r.get("agentId")),
            "zip": _norm(r.get("memberZip")),
        }
        rows.append(rec)
        if rec["mbi"]:
            by_mbi[rec["mbi"]] = rec
        if rec["member_number"]:
            by_member[rec["member_number"]] = rec
    return rows, by_mbi, by_member, pending


def main(path):
    app = create_app()
    with app.app_context():
        bob_rows, bob_by_mbi, bob_by_member, pending = load_bob(path)
        bob_mbis = set(bob_by_mbi)
        bob_members = set(bob_by_member)
        print(f"BOB active rows: {len(bob_rows)}  unique MBI: {len(bob_mbis)}  unique memberNumber: {len(bob_members)}")
        print(f"BOB pending-term (2026-07-31, switching): {len(pending)}")

        # DB active UHC policies
        uhc = (Policy.query
               .filter(Policy.carrier == "UHC", Policy.status == "active")
               .all())
        print(f"\nDB active UHC policies: {len(uhc)}")

        # ---- Direction 1: DB active policies NOT matched in BOB (the over-count) ----
        db_unmatched = []
        matched_bob_mbis = set()
        matched_bob_members = set()
        for p in uhc:
            pm = _norm(p.member_id)
            pmbi = _norm(p.mbi)
            hit = None
            if pmbi and pmbi in bob_by_mbi:
                hit = bob_by_mbi[pmbi]
            elif pm and pm in bob_by_member:
                hit = bob_by_member[pm]
            elif pm and pm in bob_by_mbi:           # member_id sometimes holds an MBI
                hit = bob_by_mbi[pm]
            elif pmbi and pmbi in bob_by_member:
                hit = bob_by_member[pmbi]
            if hit:
                matched_bob_mbis.add(hit["mbi"])
                matched_bob_members.add(hit["member_number"])
            else:
                cust = Customer.query.get(p.customer_id) if p.customer_id else None
                agent = User.query.get(p.agent_id) if p.agent_id else None
                db_unmatched.append({
                    "policy_id": p.id,
                    "customer_id": p.customer_id,
                    "name": (cust.full_name if cust else ""),
                    "dob": (str(cust.dob) if cust and cust.dob else ""),
                    "member_id": p.member_id,
                    "mbi": p.mbi or (cust.mbi if cust else ""),
                    "plan_name": p.plan_name,
                    "plan_type": p.plan_type,
                    "eff": str(p.effective_date) if p.effective_date else "",
                    "term_date": str(p.term_date) if p.term_date else "",
                    "agent": (agent.name if agent else ""),
                })

        # ---- Direction 2: BOB active people NOT found active in the DB (under-count) ----
        db_active_mbis = {_norm(p.mbi) for p in uhc if _norm(p.mbi)}
        db_active_members = {_norm(p.member_id) for p in uhc if _norm(p.member_id)}
        bob_unmatched = []
        for rec in bob_rows:
            if (rec["mbi"] in db_active_mbis or rec["member_number"] in db_active_members
                    or rec["mbi"] in db_active_members or rec["member_number"] in db_active_mbis):
                continue
            bob_unmatched.append(rec)

        print(f"\n=== DIRECTION 1: DB active NOT in BOB (over-count candidates): {len(db_unmatched)} ===")
        # bucket by has-term-date (genuine term) vs not
        with_term = [r for r in db_unmatched if r["term_date"]]
        no_term = [r for r in db_unmatched if not r["term_date"]]
        print(f"   with a term_date already set (should not be status=active — data bug): {len(with_term)}")
        print(f"   no term_date (need a reason: switcher / stale / off-book): {len(no_term)}")

        print(f"\n=== DIRECTION 2: BOB active NOT active in DB (under-count / missing): {len(bob_unmatched)} ===")

        # write full report
        out = "scripts/uhc_reconcile_report.csv"
        with open(out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["direction", "policy_id", "customer_id", "name", "dob",
                        "member_id", "mbi", "plan", "plan_type", "eff", "term_date", "agent"])
            for r in db_unmatched:
                w.writerow(["DB_not_in_BOB", r["policy_id"], r["customer_id"], r["name"], r["dob"],
                            r["member_id"], r["mbi"], r["plan_name"], r["plan_type"], r["eff"],
                            r["term_date"], r["agent"]])
            for r in bob_unmatched:
                w.writerow(["BOB_not_in_DB", "", "", f"{r['first']} {r['last']}", r["dob"],
                            r["member_number"], r["mbi"], r["plan"], "", r["eff"], "", ""])
        print(f"\nwrote {out}  ({len(db_unmatched)} DB-side + {len(bob_unmatched)} BOB-side)")
        print("\nNET: DB active", len(uhc), "vs BOB active", len(bob_rows),
              f"=> over-count {len(uhc) - len(bob_rows):+d}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "docs/Carrier BOB DL/July 2026 period/UHC/UHC book of business.xlsx")
