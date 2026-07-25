from app.plan_lane import plan_lane, resolve_primary_medical
from datetime import date


class _P:
    """Minimal policy stub."""
    def __init__(self, pid, plan_type, code, eff, status="active"):
        self.id = pid; self.plan_type = plan_type; self.contract_code = code
        self.effective_date = eff; self.status = status


def test_primary_medical_lane():
    for t in ("mapd", "MAPD", "ma", "dsnp", "csnp", "pdp", "PDP"):
        assert plan_lane(t) == "primary_medical", t


def test_medigap_lane():
    for t in ("medigap", "ms", "MS"):
        assert plan_lane(t) == "medigap", t


def test_ancillary_lane():
    for t in ("dvh", "dental", "hi", "hospital_indemnity", "gtl", "life"):
        assert plan_lane(t) == "ancillary", t


def test_other_lane():
    for t in ("", None, "something_unknown"):
        assert plan_lane(t) == "other", repr(t)


def test_resolve_overcash_supersede():
    # Aetna PDP 2024 (S-code) vs UHC MAPD 2026 (H-code): diff codes, UHC newer.
    aetna = _P(1, "pdp", "S5601-017", date(2024, 1, 1))
    uhc = _P(2, "mapd", "H5253-117", date(2026, 1, 1))
    r = resolve_primary_medical([aetna, uhc])
    assert r["current"] is uhc
    assert r["supersede"] == [aetna]
    assert r["needs_review"] is False


def test_resolve_renewal_same_code_no_term():
    # Same contract code across years = renewal, NOT supersession.
    a = _P(1, "mapd", "H1036-335", date(2025, 1, 1))
    b = _P(2, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True        # same code = can't auto-resolve -> review


def test_resolve_missing_code_needs_review():
    a = _P(1, "mapd", None, date(2025, 1, 1))
    b = _P(2, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True


def test_resolve_eff_tie_needs_review():
    a = _P(1, "mapd", "H1036-335", date(2026, 1, 1))
    b = _P(2, "mapd", "H9999-001", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True


def test_resolve_single_primary_medical():
    a = _P(1, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a])
    assert r["current"] is a and r["supersede"] == [] and r["needs_review"] is False


def test_resolve_ignores_non_primary_medical():
    # Benson-shape: medigap + dvh -> NO primary-medical -> nothing to resolve.
    mg = _P(1, "ms", "G", date(2025, 9, 1))
    dvh = _P(2, "dvh", None, date(2025, 9, 1))
    r = resolve_primary_medical([mg, dvh])
    assert r["current"] is None and r["supersede"] == [] and r["needs_review"] is False


def test_resolve_only_active():
    a = _P(1, "mapd", "H1036-335", date(2024, 1, 1), status="termed")
    b = _P(2, "mapd", "H9999-001", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    # the termed one is out of scope -> only b remains -> single current, no supersede
    assert r["current"] is b and r["supersede"] == [] and r["needs_review"] is False
