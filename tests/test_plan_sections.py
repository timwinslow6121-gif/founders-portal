# tests/test_plan_sections.py
from app.plan_sections import (coverage_category, sections_for,
                               oop_cap_for_year, medigap_coverage)


class _Plan:
    def __init__(self, plan_type, year=2026, plan_letter=None):
        self.plan_type = plan_type
        self.year = year
        self.plan_letter = plan_letter


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
