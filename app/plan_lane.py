"""Lane classifier for the corrected lane-aware merge (spec
docs/superpowers/specs/2026-07-24-corrected-lane-aware-merge-design.md).

A plan's LANE decides whether it can coexist with another plan on one person, or
whether a newer plan supersedes it. PURE + on-demand — never persisted, never
overwrites plan_type. The specific plan_type/coverage_category stays intact for
all filtering (HI vs DVH vs Life stay distinguishable).

  primary_medical : MAPD, MA-only, PDP  -> exactly ONE active at a time
  medigap         : Medigap/MS          -> free coexist, never auto-term
  ancillary       : DVH, HI, Life       -> free coexist, never auto-term
  other           : unknown             -> never auto-term
"""
from app.plan_sections import coverage_category

_LANE_OF_CATEGORY = {
    "part_c": "primary_medical",
    "pdp": "primary_medical",
    "medigap": "medigap",
    "dvh": "ancillary",
    "hospital_indemnity": "ancillary",
}


def plan_lane(plan_type):
    """Map a plan_type string to its merge lane. 'life' (not in coverage_category)
    is ancillary; everything unknown is 'other'."""
    pt = (plan_type or "").strip().lower()
    if pt == "life":
        return "ancillary"
    # dsnp and csnp are Part C SNP variants (primary_medical)
    if pt in ("dsnp", "csnp"):
        return "primary_medical"
    cat = coverage_category(plan_type)
    return _LANE_OF_CATEGORY.get(cat, "other")
