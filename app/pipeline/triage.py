"""
Tier rules (SPEC 5.2), in evaluation order.

Tiers, not a 0-100 score: every tier must be explainable in one sentence to the
agent looking at it.

This module returns INGREDIENTS, never a sentence. reason_code is an enum the
template maps to plain language; plan_id / county / days_left let it interpolate
"H5525-035 is not offered in Cabarrus County for 2027" without SQL building
strings.
"""
import datetime as dt
from typing import NamedTuple, Optional

from app.extensions import db
from app.models import PlanRating, SarRule
from app.pipeline.plans import current_plan_for


class Tier(NamedTuple):
    tier: int
    rank: int
    reason_code: str
    plan_id: Optional[int] = None
    county: Optional[str] = None
    days_left: Optional[int] = None


def _days(a, b):
    return (b - a).days


def tier_for(customer, state, cfg, today=None):
    today = today or dt.date.today()

    # 10. Manual override beats every rule above it.
    if state.tier_override:
        return Tier(state.tier_override, 0, "override")

    if state.track == "lead":
        return _lead_tier(state, cfg, today)
    return _renewal_tier(customer, state, cfg, today)


def _renewal_tier(customer, state, cfg, today):
    cp = current_plan_for(customer.id, customer.agency_id)
    plan_id = cp["plan_id"] if cp else None
    county = cp["county"] if cp else None

    # 1. Plan is ending in their county.
    #
    # Case-INSENSITIVE on purpose. Production county values are inconsistent
    # with themselves -- 'CABARRUS' (2,332) alongside 'ROWAN' (1,449) and
    # 'Rowan' (25) -- because they arrive from different carrier BOB exports.
    # An exact match silently returned ZERO for the one real SAR case we have
    # (Humana H5525-035 exiting Cabarrus: 14 customers, all missed), and a
    # missed SAR is the highest-severity failure this feature has: the member
    # loses coverage or is auto-assigned without ever being called.
    if plan_id and county:
        sar = (SarRule.query
               .filter(SarRule.agency_id == customer.agency_id,
                       SarRule.plan_id == plan_id,
                       db.func.upper(db.func.trim(SarRule.county))
                       == county.strip().upper())
               .first())
        if sar:
            return Tier(1, 1, "sar", plan_id, county)

    # 2. NC State Health Plan retiree who has not confirmed their opt-out call.
    if cfg.shp_enabled and state.shp_flag and state.shp_confirmed_at is None:
        left = _days(today, cfg.shp_end) if cfg.shp_end else None
        if left is not None and left < 0:
            return Tier(1, 0, "shp_closed", plan_id, county, left)
        return Tier(1, 0 if (left or 99) <= 7 else 2, "shp_pending", plan_id, county, left)

    # 3-6. Plan rating.
    rating = None
    if plan_id:
        row = PlanRating.query.filter_by(
            agency_id=customer.agency_id, plan_id=plan_id
        ).first()
        rating = row.rating if row else None

    if rating == 1:
        return Tier(1, 3, "rating_major", plan_id, county)
    if rating == 2:
        return Tier(2, 4, "rating_some", plan_id, county)
    if rating == 3:
        return Tier(3, 6, "rating_little", plan_id, county)
    return Tier(2, 5, "unrated", plan_id, county)


def _lead_tier(state, cfg, today):
    # 7-9. Urgency comes from a date, not a category.
    if not state.sep_end:
        return Tier(2, 5, "no_deadline")
    left = _days(today, state.sep_end)
    if left < 0:
        return Tier(2, 4, "sep_closed", days_left=left)
    if left <= cfg.sep_days:
        return Tier(1, 1 if left <= 7 else 2, "sep_urgent", days_left=left)
    return Tier(2, 4, "sep_future", days_left=left)
