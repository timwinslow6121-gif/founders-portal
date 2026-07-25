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


def _default_type_of(p):
    return getattr(p, "plan_type", None)


def _default_code_of(p):
    return getattr(p, "contract_code", None)


def resolve_primary_medical(policies, plan_type_of=None, code_of=None):
    """Decide which primary-medical plan is current and which older ones to term.

    Auto-supersede ONLY when unambiguous: two+ active primary-medical policies
    with KNOWN DIFFERENT contract codes AND exactly one strictly-newer effective
    date. Otherwise term nothing and flag needs_review. Medigap/ancillary/other
    are never in scope. Callers may pass plan_type_of/code_of accessors to supply
    the EFFECTIVE type/code (e.g. falling back to the linked Plan when blank)."""
    type_of = plan_type_of or _default_type_of
    code_of = code_of or _default_code_of

    pm = [p for p in policies
          if getattr(p, "status", "active") == "active"
          and plan_lane(type_of(p)) == "primary_medical"]

    if len(pm) <= 1:
        return {"current": pm[0] if pm else None, "supersede": [], "needs_review": False}

    # 2+ primary-medical. Unambiguous only when all codes known + all distinct +
    # a single strict-newest effective date.
    codes = [(code_of(p) or "").strip().upper() for p in pm]
    effs = [getattr(p, "effective_date", None) for p in pm]
    if any(not c for c in codes) or len(set(codes)) != len(codes) or any(e is None for e in effs):
        return {"current": None, "supersede": [], "needs_review": True}

    newest = max(effs)
    newest_holders = [p for p, e in zip(pm, effs) if e == newest]
    if len(newest_holders) != 1:                    # eff tie -> ambiguous
        return {"current": None, "supersede": [], "needs_review": True}

    current = newest_holders[0]
    return {"current": current,
            "supersede": [p for p in pm if p is not current],
            "needs_review": False}
