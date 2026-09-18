"""
Resolving a customer's CURRENT plan.

There is no customers.current_plan_id -- the portal reaches a plan through
policies. Measured on production (agency 1): 5,435 customers hold >= 1 active
policy, 5,405 of those are linked to a plan, and 27 hold TWO active policies.

Those 27 are why this is not a one-line join. 15 of them are medigap+pdp: AEP
triage is about the Part C / Part D plan, so the PDP must win even when the
Medigap policy is newer. app/plan_lane.py already classifies lanes and is the
existing seam -- do not reimplement it.

NEVER branch on Policy.plan_type: it holds carrier vocabulary (2,133 active UHC
policies typed 'MA', ~15 genuinely MA-only). Read the lane from the linked Plan.
"""
from app.extensions import db
from app.models import Policy, Plan, Customer
from app.plan_lane import plan_lane

_LANE_RANK = {"primary_medical": 0, "medigap": 1, "ancillary": 2, "other": 3}


def current_plan_for(customer_id, agency_id):
    """The plan this customer should be triaged on, or None.

    Returns {plan_id, policy_id, county, lane, ambiguous} where `ambiguous` is
    True when two policies share the winning lane -- the caller may surface that
    for review rather than trusting the pick silently.
    """
    rows = (
        db.session.query(Policy, Plan)
        .join(Plan, Plan.id == Policy.plan_id)
        .filter(
            Policy.customer_id == customer_id,
            Policy.agency_id == agency_id,
            Policy.status == "active",
            Policy.plan_id.isnot(None),
        )
        .all()
    )
    if not rows:
        return None

    def sort_key(pair):
        policy, plan = pair
        lane = plan_lane(plan.plan_type)
        return (
            _LANE_RANK.get(lane, 9),
            -(policy.effective_date.toordinal() if policy.effective_date else 0),
            -policy.id,
        )

    rows.sort(key=sort_key)
    policy, plan = rows[0]
    lane = plan_lane(plan.plan_type)

    ambiguous = sum(1 for p, pl in rows if plan_lane(pl.plan_type) == lane) > 1

    customer = db.session.get(Customer, customer_id)
    county = (customer.county or "").strip() or (policy.county or "").strip() or None

    return {
        "plan_id": plan.id,
        "policy_id": policy.id,
        "county": county,
        "lane": lane,
        "ambiguous": ambiguous,
    }
