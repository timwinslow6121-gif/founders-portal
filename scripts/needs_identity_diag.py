"""Read-only: dump the 3 Needs-Identity hub buckets (interval / match / name)."""
from app import create_app
from app.customers import _needs_interval_items, _needs_match_items, _needs_name_items


def main():
    app = create_app()
    with app.app_context():
        aid = 1
        iv = _needs_interval_items(aid)
        mt = _needs_match_items(aid)
        nm = _needs_name_items(aid)
        print(f"NEEDS INTERVAL: {len(iv)} | NEEDS MATCH: {len(mt)} | NEEDS NAME: {len(nm)}")

        print("\n=== NEEDS INTERVAL (has an agent but no AOR history chapter) ===")
        for x in iv:
            c = x["c"]
            print(f"  cust {c.id} | {c.full_name} | dob {c.dob} | mbi {c.mbi} | "
                  f"agent {x['agent_name']} | stub={c.stub}")

        print("\n=== NEEDS MATCH (NULL-customer commission line items + suggested match) ===")
        for x in mt:
            li = x["li"]
            print(f"  li {li.id} | {li.carrier} | {li.member_name!r} | mbi {li.mbi} | "
                  f"carrier_id {li.carrier_member_id} | class {li.classification} | "
                  f"${li.raw_amount} | SUGGESTS -> cust {x['suggested_customer_id']} "
                  f"{x['suggested_customer_name']!r} (tier {x['tier']})")

        print("\n=== NEEDS NAME (active policies, blank first+last) ===")
        for x in nm:
            p = x["p"]
            print(f"  pid {p.id} | {p.carrier} | member_id {p.member_id} | mbi {p.mbi} | "
                  f"plan {p.plan_name!r} | cust {p.customer_id}")


if __name__ == "__main__":
    main()
