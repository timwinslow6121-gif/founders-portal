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
