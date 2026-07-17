"""Read-only: why do same-name+same-dob duplicates remain? Show each remaining
cluster with its signal + WHY it's not auto-merging (blocked-by-AOR-bug vs conflict)."""
from collections import Counter
from app import create_app
from app.dedup import find_no_mbi_clusters
from app.models import Customer, CustomerAorHistory, Policy


def main():
    app = create_app()
    with app.app_context():
        aid = 1
        clusters = find_no_mbi_clusters(aid)
        print("TOTAL remaining clusters:", len(clusters))
        print("by signal:", dict(Counter(c.signal for c in clusters)))
        print()

        # Focus: clusters where ALL rows share name+dob AND same primary_agent_id
        # (Tim's "same name, same dob, same writing agent" — these SHOULD be mergeable)
        same_agent_samedob = []
        for cl in clusters:
            ids = [cl.keeper_id] + [i for i in cl.member_ids if i != cl.keeper_id]
            rows = [Customer.query.get(i) for i in ids]
            dobs = {r.dob for r in rows if r.dob}
            agents = {r.primary_agent_id for r in rows}
            if len(dobs) == 1 and len(agents) == 1 and None not in agents:
                same_agent_samedob.append((cl, rows))

        print(f"clusters where all rows share ONE dob AND one agent: {len(same_agent_samedob)}")
        print("  (these are Tim's 'same name/dob/agent' dups — expected to be mergeable)\n")

        for cl, rows in same_agent_samedob:
            # why isn't it dob_match? show signal + mbi state + AOR overlap
            mbis = {r.mbi for r in rows if r.mbi}
            has_aor = any(CustomerAorHistory.query.filter_by(customer_id=r.id).count() for r in rows)
            reason = []
            if cl.signal == "conflict":
                reason.append("CONFLICT signal")
            if len(mbis) > 1:
                reason.append(f"{len(mbis)} different MBIs")
            if cl.signal in ("dob_match", "shared_id") and has_aor:
                reason.append("blocked by AOR-merge engine bug")
            print(f"  [{cl.signal}] {rows[0].full_name} dob {rows[0].dob} agent {rows[0].primary_agent_id} "
                  f"| rows {[(r.id, r.mbi, r.stub) for r in rows]} | {' + '.join(reason) or 'mergeable?'}")


if __name__ == "__main__":
    main()
