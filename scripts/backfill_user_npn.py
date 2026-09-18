"""
Backfill users.npn from agent_carrier_contracts, refusing anything ambiguous.

An NPN is a per-PERSON national identifier. It was only ever stored in
agent_carrier_contracts.id_value keyed by id_type -- one row per carrier, so up
to 8 copies per agent that could disagree. They did: Alex Groves' rows labelled
"NPN" actually hold his Humana SAN (2018284) and his UHC agent number (6775603).
His real NPN is 22204954.

Gates (refuse rather than guess -- a wrong NPN scopes an API credential to the
wrong producer's book):
  1. only id_type='NPN' rows are considered
  2. the agent's NPN rows must AGREE on a single value; disagreement -> refuse
  3. a value that also appears under a carrier-specific id_type for that agent
     (writing_number / agent_code / SAN) is suspect -> refuse
  4. never overwrite an existing users.npn
  5. KNOWN_CORRECTIONS are applied explicitly, from Tim, not inferred

Usage:
  ./venv/bin/python3 scripts/backfill_user_npn.py            # dry run
  ./venv/bin/python3 scripts/backfill_user_npn.py --apply
"""
import sys, os, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import User
from sqlalchemy import text

# Values Tim supplied directly. Alex's stored "NPN" rows are NOT his NPN.
KNOWN_CORRECTIONS = {
    "alex@foundersinsuranceagency.com": "22204954",
}


def run(apply=False):
    app = create_app()
    with app.app_context():
        rows = db.session.execute(text(
            "SELECT agent_id, carrier, id_type, id_value FROM agent_carrier_contracts "
            "WHERE id_value IS NOT NULL AND trim(id_value) <> ''"
        )).fetchall()

        by_agent = collections.defaultdict(lambda: collections.defaultdict(set))
        for agent_id, carrier, id_type, id_value in rows:
            by_agent[agent_id][(id_type or "").strip().upper()].add(id_value.strip())

        planned, refused = [], []
        for u in User.query.order_by(User.id).all():
            if u.npn:
                continue

            forced = KNOWN_CORRECTIONS.get((u.email or "").lower())
            if forced:
                planned.append((u, forced, "explicit correction (Tim)"))
                continue

            types = by_agent.get(u.id, {})
            npns = types.get("NPN", set())
            if not npns:
                refused.append((u, "no NPN row on any carrier contract"))
                continue
            if len(npns) > 1:
                refused.append((u, f"NPN rows disagree: {sorted(npns)}"))
                continue

            value = next(iter(npns))
            carrier_scoped = set()
            for t, vals in types.items():
                if t != "NPN":
                    carrier_scoped |= vals
            if value in carrier_scoped:
                refused.append((u, f"{value} also appears as a carrier-specific id -- suspect"))
                continue

            planned.append((u, value, "agreed across carrier contracts"))

        print(f"{'APPLY' if apply else 'DRY RUN'} -- users.npn backfill\n")
        print("WILL SET")
        for u, value, why in planned:
            print(f"  {u.id:<4} {(u.name or '')[:24]:<24} npn={value:<12} ({why})")
        print("\nREFUSED (left NULL -- needs a human)")
        for u, why in refused:
            print(f"  {u.id:<4} {(u.name or '')[:24]:<24} {why}")

        if apply:
            for u, value, _ in planned:
                u.npn = value
            db.session.commit()
            print(f"\nApplied: {len(planned)} set, {len(refused)} refused.")
        else:
            print(f"\nDry run: {len(planned)} would be set, {len(refused)} refused. "
                  f"Re-run with --apply.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    run(ap.parse_args().apply)
