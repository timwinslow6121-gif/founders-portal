"""Read-only: list active policies with no agent_id, and what the BOB's agentId says
for each (the BOB carries the writing agent per member → we can re-attribute)."""
import pandas as pd
from app import create_app
from app.models import Policy, Customer, User, AgentCarrierContract

BOB_PATH = "/tmp/uhc_bob.xlsx"


def norm(s):
    return str(s).strip().upper() if s is not None and str(s) != "nan" else ""


def main():
    app = create_app()
    with app.app_context():
        # BOB: mbi -> agentId + agentName
        bob = pd.read_excel(BOB_PATH, header=2, dtype=str).dropna(how="all")
        bob = bob[bob["policyTermDate"] == "2300-01-01"]
        bob_agent = {}
        for _, r in bob.iterrows():
            if norm(r["mbiNumber"]):
                bob_agent[norm(r["mbiNumber"])] = (norm(r["agentId"]), norm(r["agentName"]))

        # UHC writing-id -> our User (from AgentCarrierContract), same map the ledger uses
        contracts = {}
        for c in AgentCarrierContract.query.all():
            if c.id_value:
                contracts[norm(c.id_value)] = c.agent_id

        uhc = Policy.query.filter_by(carrier="UHC", status="active", agent_id=None).all()
        allc = Policy.query.filter_by(status="active", agent_id=None).count()
        print(f"UHC active, agent_id=None: {len(uhc)}")
        print(f"ALL carriers active, agent_id=None: {allc}\n")

        for p in uhc:
            c = Customer.query.get(p.customer_id) if p.customer_id else None
            name = c.full_name if c else "?"
            cust_agent = c.primary_agent_id if c else None
            ba = bob_agent.get(norm(p.mbi))
            resolves = contracts.get(ba[0]) if ba else None
            ruser = User.query.get(resolves).name if resolves else None
            print(f"pid {p.id} | {name} | {p.plan_name or '(blank)'} [{p.plan_type}] | mbi {p.mbi}")
            print(f"    cust.primary_agent_id={cust_agent} | agent_id_carrier={p.agent_id_carrier} | "
                  f"BOB agentId={ba[0] if ba else '-'} ({ba[1] if ba else '-'}) -> our user={ruser or '(no contract map)'}")


if __name__ == "__main__":
    main()
