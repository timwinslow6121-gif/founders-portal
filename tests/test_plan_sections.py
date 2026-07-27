# tests/test_plan_sections.py
from app.plan_sections import (coverage_category, sections_for,
                               oop_cap_for_year, medigap_coverage,
                               kpis_for, top_extra_benefits, PART_B_PREMIUM_2026)


class _Plan:
    def __init__(self, plan_type, year=2026, plan_letter=None):
        self.plan_type = plan_type
        self.year = year
        self.plan_letter = plan_letter


def _plan(plan_type, year=2026, plan_letter=None):
    return _Plan(plan_type, year=year, plan_letter=plan_letter)


def test_coverage_category_groups_part_c():
    assert coverage_category("mapd") == "part_c"
    assert coverage_category("ma") == "part_c"
    assert coverage_category("pdp") == "pdp"
    assert coverage_category("medigap") == "medigap"
    assert coverage_category("dvh") == "dvh"
    assert coverage_category("gtl") == "hospital_indemnity"
    assert coverage_category("weird") == "other"


def test_mapd_includes_drugs_group_but_ma_does_not():
    mapd_titles = [g["title"] for g in sections_for(_Plan("mapd"))]
    ma_titles = [g["title"] for g in sections_for(_Plan("ma"))]
    assert "Drugs" in mapd_titles
    assert "Drugs" not in ma_titles
    # both are Part C so both have Costs + Medical services
    assert "Costs" in mapd_titles and "Costs" in ma_titles


def test_pdp_sections_have_no_medical_group():
    titles = [g["title"] for g in sections_for(_Plan("pdp"))]
    assert "Drugs" in titles
    assert "Medical services" not in titles


def test_part_c_has_otc_and_dental_blocks():
    extras = [g for g in sections_for(_Plan("mapd")) if g["title"] == "Extras"][0]
    assert "otc" in extras["blocks"]
    assert "dental" in extras["blocks"]


def test_oop_cap_by_year():
    assert oop_cap_for_year(2025) == "$2,000"
    assert oop_cap_for_year(2026) == "$2,100"
    assert oop_cap_for_year(2027) == "$2,400"
    assert oop_cap_for_year(2099) is None


def test_medigap_grid_plan_g_covers_part_b_deductible_no():
    rows = dict(medigap_coverage("G"))
    # Plan G covers everything EXCEPT the Part B deductible
    assert rows["Part A deductible"] == "Yes"
    assert rows["Part B deductible"] == "No"
    assert rows["Part B excess charges"] == "Yes"


def test_medigap_unknown_letter_empty():
    assert medigap_coverage("Z") == []


def test_part_b_constant_present():
    assert PART_B_PREMIUM_2026 == 185.00


def test_top_extra_benefits_omits_missing():
    d = {"otc_allowance": "$45/quarter", "dental_allowance": "$2,000",
         "vision_allowance": None}
    items = top_extra_benefits(d)
    assert any("$45/quarter" in i for i in items)
    assert any("$2,000" in i for i in items)
    assert all("None" not in i for i in items)          # no None leakage
    assert len(items) == 2                                # eyewear omitted


def test_kpis_part_c_mapd_has_premium_moop_gradient():
    d = {"monthly_premium": "$0.00", "annual_oopm": "$4,500",
         "otc_allowance": "$45/quarter"}
    kinds = [k["kind"] for k in kpis_for(_plan("mapd"), d)]
    assert "premium" in kinds
    assert "gradient" in kinds                            # Top Extra Benefits card
    prem = [k for k in kpis_for(_plan("mapd"), d) if k["kind"] == "premium"][0]
    assert "185.00" in (prem["note"] or "")              # Part-B transparency note
    assert prem["value"] == "$0.00"                       # $0 premium still shows


def test_kpis_omit_missing_no_na_cards():
    # A Part C plan with NO oopm value must not emit a MOOP card at all
    d = {"monthly_premium": "$12.00"}
    labels = [k["label"] for k in kpis_for(_plan("mapd"), d)]
    assert not any("out-of-pocket" in l.lower() for l in labels)
    assert all(k["value"] for k in kpis_for(_plan("mapd"), d))  # never empty


def test_kpis_pdp_has_premium_and_rx_deductible():
    d = {"monthly_premium": "$8.00", "drug_deductible": "$545"}
    labels = [k["label"].lower() for k in kpis_for(_plan("pdp"), d)]
    assert any("premium" in l for l in labels)
    assert any("deductible" in l for l in labels)
    # PDP gets no gradient Top-Extra-Benefits card
    assert all(k["kind"] != "gradient" for k in kpis_for(_plan("pdp"), d))


def test_kpis_medigap_premium_is_age_rated_note():
    d = {}
    kpis = kpis_for(_plan("medigap", plan_letter="G"), d)
    prem = [k for k in kpis if "premium" in k["label"].lower()][0]
    assert "age-rated" in (prem["value"] + (prem["note"] or "")).lower()


def test_kpis_dvh_has_annual_max_when_present_else_omitted():
    with_max = kpis_for(_plan("dvh"), {"annual_max": "$3,000"})
    assert any("annual" in k["label"].lower() for k in with_max)
    without = kpis_for(_plan("dvh"), {})
    assert without == [] or all(k["value"] for k in without)


def test_kpis_hospital_indemnity_base_benefit():
    d = {"hi_hospital_confinement": "$300/day"}
    kpis = kpis_for(_plan("gtl"), d)
    assert any("$300/day" in k["value"] for k in kpis)
