"""Per-plan-type section config for the condensed-SOB plan snapshot page.

sections_for(plan) returns the ordered benefit groups to render for that plan's
type. Each group: {"title", "rows": [(label, details_json_key)], "blocks": [names]}.
Only relevant groups/rows are returned per type — the template never renders an
empty row for a field that doesn't apply. See
docs/superpowers/specs/2026-07-13-plan-snapshot-per-type-redesign.md
"""

_PART_C = {"ma", "mapd"}


def coverage_category(plan_type):
    pt = (plan_type or "").lower()
    if pt in _PART_C:
        return "part_c"
    if pt == "pdp":
        return "pdp"
    if pt in ("medigap", "ms"):
        return "medigap"
    if pt in ("dvh", "dental"):
        return "dvh"
    if pt in ("gtl", "hospital_indemnity", "hi"):
        return "hospital_indemnity"
    return "other"


# Part C groups. Rows are (display_label, details_json_key). Keys map to the flat
# Plan.details_json dict + a few real Plan columns surfaced by the route as details.
_PART_C_COSTS = [
    ("Monthly premium", "monthly_premium"),
    ("Medical deductible", "medical_deductible"),
    ("Annual out-of-pocket max", "annual_oopm"),
    ("Part-B giveback", "part_b_giveback"),
]
_PART_C_MEDICAL = [
    ("PCP copay", "pcp_copay"),
    ("Specialist copay", "specialist_copay"),
    ("Outpatient hospital", "outpatient_hospital"),
    ("Inpatient hospital", "inpatient_hospital"),
    ("X-ray / MRI / CT", "imaging"),
    ("PT / OT / ST", "therapy"),
    ("ER copay", "er_copay"),
    ("Urgent care", "urgent_care_copay"),
    ("Ambulance (ground)", "ambulance_ground"),
    ("Ambulance (air)", "ambulance_air"),
    ("SNF (days 1-20)", "snf"),
]
_PART_C_EXTRAS = [
    ("Gym", "gym"),
    ("Transportation", "transportation"),
    ("Vision", "vision_allowance"),
    ("Hearing", "hearing_allowance"),
]
_PART_C_DRUGS = [
    ("Rx deductible", "drug_deductible"),
    ("Tier 1", "drug_tier1"),
    ("Tier 2", "drug_tier2"),
    ("Tier 3", "drug_tier3"),
    ("Tier 4", "drug_tier4"),
    ("Tier 5", "drug_tier5"),
]
_PDP_ROWS = [
    ("Monthly premium", "monthly_premium"),
    ("Annual Rx deductible", "drug_deductible"),
    ("Preferred pharmacies", "preferred_pharmacy_note"),
]
_PDP_DRUGS = [
    ("Tier 1", "drug_tier1"), ("Tier 2", "drug_tier2"), ("Tier 3", "drug_tier3"),
    ("Tier 4", "drug_tier4"), ("Tier 5", "drug_tier5"),
]
_DVH_ROWS = [
    ("Annual benefit max", "annual_max"),
    ("Deductible", "dvh_deductible"),
    ("Vision", "vision_allowance"),
    ("Hearing", "hearing_allowance"),
    ("Waiting periods", "waiting_periods"),
]
_MEDIGAP_ROWS = [
    ("Household discount", "household_discount"),
    ("Rate type", "rate_type"),
]
_HI_BASE = [
    ("Hospital confinement (daily)", "hi_hospital_confinement"),
    ("Max benefit period (days)", "hi_max_days"),
    ("Observation / short stay", "hi_observation"),
    ("ER (injury)", "hi_er"),
    ("Mental health (daily)", "hi_mental_health"),
    ("SNF (daily)", "hi_snf"),
]


# Single labeled constant — the standard Medicare Part B premium for the year.
# NOT stored per-plan, NOT invented. Update yearly.
PART_B_PREMIUM_2026 = 185.00


def top_extra_benefits(details):
    """The OTC / Dental / Eyewear lines for the Part C gradient card.
    Each line is omitted when its source value is empty — no fabricated rows."""
    out = []
    otc = details.get("otc_allowance")
    if otc:
        out.append(f"{otc} OTC credit")
    dental = details.get("dental_allowance")
    if dental:
        out.append(f"{dental} Dental allowance")
    vision = details.get("vision_allowance")
    if vision:
        out.append(f"{vision} Eyewear allowance")
    return out


def _card(label, value, kind="plain", note=None, items=None):
    return {"label": label, "value": value, "kind": kind, "note": note,
            "items": items}


def kpis_for(plan, details):
    """Ordered headline KPI cards for this plan's type. A card whose value is
    missing is OMITTED (never rendered as N/A). See spec Section 2."""
    cat = coverage_category(plan.plan_type)
    kpis = []

    if cat == "part_c":
        premium = details.get("monthly_premium")
        if premium:
            note = f"+ ${PART_B_PREMIUM_2026:,.2f}/mo Part B ({plan.year})"
            kpis.append(_card("Monthly premium", premium, kind="premium", note=note))
        moop = details.get("annual_oopm")
        if moop:
            kpis.append(_card("Annual out-of-pocket max", moop))
        extras = top_extra_benefits(details)
        if extras:
            kpis.append(_card("Top extra benefits", "", kind="gradient", items=extras))
        return kpis

    if cat == "pdp":
        premium = details.get("monthly_premium")
        if premium:
            kpis.append(_card("Monthly premium", premium))
        ded = details.get("drug_deductible")
        if ded:
            kpis.append(_card("Annual Rx deductible", ded))
        return kpis

    if cat == "medigap":
        # Medigap is age-rated — there is no single stored premium.
        kpis.append(_card("Monthly premium", "Age-rated",
                          note="See quote — premium depends on age"))
        return kpis

    if cat == "dvh":
        amax = details.get("annual_max")
        if amax:
            kpis.append(_card("Annual benefit max", amax))
        ded = details.get("dvh_deductible")
        if ded:
            kpis.append(_card("Deductible", ded))
        return kpis

    if cat == "hospital_indemnity":
        base = details.get("hi_hospital_confinement")
        if base:
            kpis.append(_card("Hospital confinement (daily)", base))
        days = details.get("hi_max_days")
        if days:
            kpis.append(_card("Max benefit period", f"{days} days"))
        return kpis

    return kpis


def _block_has_content(block, details, medigap_rows):
    """Would a benefit block actually render anything? Mirrors the template macros'
    render conditions (otc_block/dental_block/medigap_block/hi_riders_block)."""
    if block == "otc":
        return bool(details.get("otc_allowance"))
    if block == "dental":
        return bool(details.get("dental_prev_innet")
                    or details.get("dental_major_innet")
                    or details.get("dental_allowance"))
    if block == "medigap_grid":
        return bool(medigap_rows)
    if block == "hi_riders":
        return bool(details.get("hi_riders"))
    return False


def benefit_body_is_empty(sections, details, medigap_rows, oop_cap):
    """True when the benefit sections would render ZERO content — no populated rows,
    no populated blocks, no OOP-cap row. Drives the "no benefit details entered yet"
    empty-state note so a plan with no SOB data shows guidance instead of blank cards.
    Matches the template's actual render conditions (a row shows only when its key is
    truthy in `details`)."""
    for group in sections:
        for _label, key in group.get("rows", []):
            if details.get(key):
                return False
        for block in group.get("blocks", []):
            if _block_has_content(block, details, medigap_rows):
                return False
        if group.get("title") == "Drugs" and oop_cap:
            return False
    return True


def sections_for(plan):
    cat = coverage_category(plan.plan_type)
    if cat == "part_c":
        groups = [
            {"title": "Costs", "rows": _PART_C_COSTS, "blocks": []},
            {"title": "Medical services", "rows": _PART_C_MEDICAL, "blocks": []},
            {"title": "Extras", "rows": _PART_C_EXTRAS, "blocks": ["otc", "dental"]},
        ]
        if (plan.plan_type or "").lower() == "mapd":
            groups.append({"title": "Drugs", "rows": _PART_C_DRUGS, "blocks": []})
        return groups
    if cat == "pdp":
        return [
            {"title": "Costs", "rows": _PDP_ROWS, "blocks": []},
            {"title": "Drugs", "rows": _PDP_DRUGS, "blocks": []},
        ]
    if cat == "medigap":
        return [{"title": "Plan", "rows": _MEDIGAP_ROWS, "blocks": ["medigap_grid"]}]
    if cat == "dvh":
        return [{"title": "Benefits", "rows": _DVH_ROWS, "blocks": ["dental"]}]
    if cat == "hospital_indemnity":
        return [{"title": "Base benefits", "rows": _HI_BASE, "blocks": ["hi_riders"]}]
    return [{"title": "Details", "rows": [], "blocks": []}]


_OOP_CAP = {2025: "$2,000", 2026: "$2,100", 2027: "$2,400"}


def oop_cap_for_year(year):
    return _OOP_CAP.get(year)


# Static CMS Medigap standardized benefit grid. Fixed data — same all carriers, all
# years. "Yes"/"No"/"50%"/"75%"/"100%" per the medicare.gov compare-plan-benefits chart.
_B = ["Part A coinsurance & hospital (365 days)", "Part B coinsurance/copay",
      "Blood (first 3 pints)", "Part A hospice coinsurance",
      "Skilled nursing facility coinsurance", "Part A deductible",
      "Part B deductible", "Part B excess charges", "Foreign travel emergency"]
MEDIGAP_GRID = {
    "A": ["Yes", "Yes", "Yes", "Yes", "No", "No", "No", "No", "No"],
    "B": ["Yes", "Yes", "Yes", "Yes", "No", "Yes", "No", "No", "No"],
    "C": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "80%"],
    "D": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "No", "80%"],
    "F": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "80%"],
    "G": ["Yes", "Yes", "Yes", "Yes", "Yes", "Yes", "No", "Yes", "80%"],
    "K": ["Yes", "50%", "50%", "50%", "50%", "50%", "No", "No", "No"],
    "L": ["Yes", "75%", "75%", "75%", "75%", "75%", "No", "No", "No"],
    "M": ["Yes", "Yes", "Yes", "Yes", "Yes", "50%", "No", "No", "80%"],
    "N": ["Yes", "Yes*", "Yes", "Yes", "Yes", "Yes", "No", "No", "80%"],
}


def medigap_coverage(letter):
    row = MEDIGAP_GRID.get((letter or "").upper())
    if not row:
        return []
    return list(zip(_B, row))
