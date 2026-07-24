from app.plan_lane import plan_lane


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
