"""Medicare Updates Hub — curated carrier-intel posts behind login.
Holds the update-type presentation map, the plan-affect count helper, and (added in the
routes task) the updates_bp blueprint.
See docs/superpowers/specs/2026-07-15-medicare-updates-hub-design.md."""
from app.extensions import db
from app.models import CarrierUpdate, Plan, Policy

# update_type -> presentation. ONE place; template + tests agree.
UPDATE_PRESENTATION = {
    "commission":     {"label": "Commission change", "icon": "dollar",    "accent": "commission"},
    "network":        {"label": "Network update",    "icon": "network",   "accent": "network"},
    "carrier_notice": {"label": "Carrier notice",    "icon": "carrier",   "accent": "carrier"},
    "training":       {"label": "Training & webinar","icon": "training",  "accent": "training"},
    "important_date": {"label": "Important date",     "icon": "calendar",  "accent": "date"},
    "general":        {"label": "General news",       "icon": "info",      "accent": "general"},
}


def plan_affect(plan_id, agency_id):
    """For a post's optional plan_id, return {plan_id, plan_name, count} where count is the
    AGENCY active-member count for that plan (same key/grain as the carrier pages), or None
    if plan_id is falsy / the plan is missing / on any error. Defensive: never raises."""
    if not plan_id:
        return None
    try:
        plan = Plan.query.filter_by(id=plan_id, agency_id=agency_id).first()
        if plan is None:
            return None
        count = (Policy.query
                 .filter(Policy.plan_id == plan_id,
                         Policy.status == "active",
                         Policy.agency_id == agency_id)
                 .count())
        return {"plan_id": plan.id, "plan_name": plan.plan_name, "count": count}
    except Exception:
        return None
