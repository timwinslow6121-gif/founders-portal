import os, pytest
from app.parsers.bcbs import parse

CSV = "docs/Carrier BOB DL/Aug 2026 period/BCBS/Tim Winslow/book_Of_business.csv"


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_parses_active_records():
    recs = parse(CSV)
    assert len(recs) > 0
    assert all(r["carrier"] == "BCBS" for r in recs)


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_address_fields_are_emitted():
    """The Aug-2026 BCBS export carries full address/contact columns.

    Regression: the parser previously emitted only phone + county, so
    _upsert_customer_from_policy (which reads address1/city/state/zip_code)
    left every imported customer with a blank address.
    """
    recs = parse(CSV)
    withaddr = [r for r in recs if r.get("address1")]
    assert withaddr, "no record carried address1 — address columns are being dropped"

    r = withaddr[0]
    assert r["city"]
    assert r["state"] == "NC"
    assert r["zip_code"]


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_identity_and_dates_present():
    recs = parse(CSV)
    r = next(x for x in recs if x.get("mbi"))
    assert r["member_id"] == r["mbi"]
    assert r["dob"] is not None
    assert r["effective_date"] is not None


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_sentinel_term_date_means_active():
    """12/31/2199 is BCBS's 'no termination' sentinel, not a real term date."""
    recs = parse(CSV)
    ma = [r for r in recs if not r.get("renewal_date")]
    assert any(r["term_date"] is None for r in ma)


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_all_mappable_columns_are_captured():
    """Every populated column the models can hold should reach the record."""
    recs = parse(CSV)
    r = next(x for x in recs if x.get("address1"))
    for key in ("phone", "email", "county", "address1", "city", "state",
                "zip_code", "gender", "carrier_member_id"):
        assert key in r, f"parser never emits {key!r}"
    assert r["gender"] in ("M", "F", "")
    # BCBSNC Member Number is the carrier's own id — keep it even when MBI is the key
    assert r["carrier_member_id"]


@pytest.mark.skipif(not os.path.exists(CSV), reason="Aug 2026 BCBS BOB fixture absent")
def test_phone_is_normalized():
    """Phones land in one canonical shape so lookups (and Quo call matching) work."""
    from app.parsers.bcbs import _normalize_phone
    assert _normalize_phone("7042814280") == "704-281-4280"
    assert _normalize_phone("(704) 281-4280") == "704-281-4280"
    assert _normalize_phone("704.281.4280") == "704-281-4280"
    assert _normalize_phone("+17042814280") == "704-281-4280"
    assert _normalize_phone("17042814280") == "704-281-4280"
    assert _normalize_phone("") == ""
    assert _normalize_phone("12345") == "12345"      # too short: leave as-is

    recs = parse(CSV)
    phones = [r["phone"] for r in recs if r.get("phone")]
    assert phones
    assert all(len(p) == 12 and p[3] == "-" and p[7] == "-" for p in phones), phones[:5]
