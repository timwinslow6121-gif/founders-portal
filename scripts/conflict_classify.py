"""Read-only: classify the remaining 'conflict' clusters (same name, diff MBI).
For each, show whether the rows share DOB + address + phone (= likely reissued-MBI
same person, safe to merge) vs differ (= different people / coexistence / switcher)."""
from app import create_app
from app.dedup import find_no_mbi_clusters
from app.models import Customer, Policy


def main():
    app = create_app()
    with app.app_context():
        clusters = [c for c in find_no_mbi_clusters(1) if c.signal == "conflict"]
        print(f"conflict clusters: {len(clusters)}\n")
        for cl in clusters:
            rows = [Customer.query.get(i) for i in cl.member_ids]
            nm = rows[0].full_name
            dobs = {r.dob for r in rows}
            addrs = {(r.address1, r.zip_code) for r in rows}
            phones = {r.phone_primary for r in rows}
            carriers = set()
            for r in rows:
                for p in Policy.query.filter_by(customer_id=r.id, status="active").all():
                    carriers.add(p.carrier)
            same_person = len(dobs) == 1 and len(addrs) == 1 and len(phones) == 1
            verdict = ("SAME PERSON (reissued MBI) — safe merge" if same_person
                       else "DIFFERS — review (switcher/coexistence/diff person)")
            print(f"  {nm}: {verdict}")
            print(f"     dobs={ {str(d) for d in dobs} } | same_addr={len(addrs)==1} | "
                  f"same_phone={len(phones)==1} | active_carriers={carriers}")
            for r in rows:
                print(f"     cust {r.id} mbi {r.mbi} dob {r.dob} addr {r.address1!r} {r.zip_code} agent "
                      f"{r.primary_agent.name if r.primary_agent else None}")


if __name__ == "__main__":
    main()
