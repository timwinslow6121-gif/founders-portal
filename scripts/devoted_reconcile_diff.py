"""READ-ONLY Devoted BOB<->DB diff. Writes NOTHING. Matches by MBI (via
customer.mbi), both directions. Mirrors the UHC reconcile-diff method.

Run on VPS:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/devoted_reconcile_diff.py
"""
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import Policy, Customer
from app.parsers.devoted import parse
from app.upload import _dedupe_bob_records

BOB = "docs/Carrier BOB DL/July 2026 period/Devoted/Devoted Book of business.xlsx"


def main():
    app = create_app()
    with app.app_context():
        # --- BOB active (after winning-app dedup) ---
        recs = parse(BOB)
        deduped = _dedupe_bob_records(recs)
        bob = [r for r in deduped if r.get("status") == "active"]
        bob_by_mbi = {r["mbi"]: r for r in bob if r.get("mbi")}
        print("BOB active (deduped):", len(bob), "| distinct MBIs:", len(bob_by_mbi))

        # --- DB active Devoted, mapped to MBI via customer ---
        dbpols = Policy.query.filter_by(carrier="Devoted", status="active").all()
        db_mbi_to_pol = {}
        db_no_mbi = []
        for p in dbpols:
            c = db.session.get(Customer, p.customer_id) if p.customer_id else None
            mbi = (c.mbi.upper() if (c and c.mbi) else None)
            if mbi:
                db_mbi_to_pol[mbi] = (p, c)
            else:
                db_no_mbi.append(p)
        print("DB active Devoted policies:", len(dbpols),
              "| with customer MBI:", len(db_mbi_to_pol), "| no MBI:", len(db_no_mbi))
        print()

        # --- the diff ---
        bob_mbis = set(bob_by_mbi)
        db_mbis = set(db_mbi_to_pol)
        in_both = bob_mbis & db_mbis
        bob_not_db = bob_mbis - db_mbis          # NEW to import
        db_not_bob = db_mbis - bob_mbis          # in DB active but NOT in BOB
        print("=== DIFF ===")
        print("  in BOTH (MBI match):", len(in_both))
        print("  BOB-not-in-DB (to IMPORT as new):", len(bob_not_db))
        print("  DB-active-not-in-BOB (investigate switcher/stale):", len(db_not_bob))
        print("  net: DB active", len(dbpols), "vs BOB active", len(bob),
              "=", ("%+d" % (len(dbpols) - len(bob))))
        print()

        if db_not_bob:
            print("  --- DB-active-not-in-BOB detail (each needs a reason) ---")
            for mbi in sorted(db_not_bob):
                p, c = db_mbi_to_pol[mbi]
                print("    %-24s mbi=%s pol=%s plan=%r eff=%s agent=%s"
                      % (c.full_name, mbi, p.id, p.plan_name, p.effective_date,
                         c.primary_agent_id))
            print()

        print("  BOB-not-in-DB by eff year:",
              dict(Counter(str(bob_by_mbi[m]["effective_date"])[:4] for m in bob_not_db)))
        print("  BOB-not-in-DB by agent:",
              dict(Counter((bob_by_mbi[m].get("agent_name") or "?") for m in bob_not_db)))
        print("  BOB-not-in-DB by plan_type:",
              dict(Counter((bob_by_mbi[m].get("plan_type") or "?") for m in bob_not_db)))


if __name__ == "__main__":
    main()
