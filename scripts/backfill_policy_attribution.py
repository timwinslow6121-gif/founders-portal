"""Re-resolve NULL-agent active policies via the (now-complete) writing-id map.

Mostly a RE-RESOLUTION pass: most IDs are already in AgentCarrierContract; they were
just never resolved at upload time. Dry-run by default. Back up the DB before --apply.
Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_policy_attribution.py [--apply]
"""
import sys
from collections import Counter
from app import create_app
from app.extensions import db
from app.models import Policy, User
from app.attribution import resolve_writing_agent

def main(apply):
    app = create_app()
    with app.app_context():
        q = (Policy.query
             .filter(Policy.status == "active", Policy.agent_id.is_(None),
                     Policy.agent_id_carrier.isnot(None), Policy.agent_id_carrier != ""))
        resolved, unresolved = Counter(), Counter()
        for p in q.all():
            aid = resolve_writing_agent(p.carrier, p.agent_id_carrier, p.agency_id)
            if aid:
                resolved[aid] += 1
                if apply:
                    p.agent_id = aid
            else:
                unresolved[(p.carrier, p.agent_id_carrier)] += 1
        if apply:
            db.session.commit()
        print(f"{'APPLIED' if apply else 'DRY-RUN'} — resolved {sum(resolved.values())} policies:")
        for aid, n in resolved.most_common():
            u = db.session.get(User, aid)
            print(f"  {n:5d}  {u.name if u else aid}")
        print(f"Unresolved (stay NULL → Unattributed view): {sum(unresolved.values())}")
        for (carrier, wid), n in unresolved.most_common(20):
            print(f"  {n:5d}  {carrier} writingID={wid!r}")

if __name__ == "__main__":
    main("--apply" in sys.argv)
