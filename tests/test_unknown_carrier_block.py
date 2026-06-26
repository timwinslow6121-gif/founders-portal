def test_unsupported_carrier_is_blocked():
    """A detected carrier not in NORMALIZERS must be rejected (no ingest)."""
    from app.commission.normalizers import NORMALIZERS
    assert "GTL" not in NORMALIZERS
    assert "Wellable" not in NORMALIZERS and "Medico" not in NORMALIZERS
    # the supported set is exactly the 6 wired carriers
    assert set(NORMALIZERS) == {"UHC", "Humana", "Devoted", "BCBS", "Aetna", "Healthspring"}


def test_block_message_lists_supported(app):
    """The guard helper returns a clear block reason for an unsupported carrier."""
    from app.commission.routes import _carrier_supported_or_reason
    ok, reason = _carrier_supported_or_reason("GTL")
    assert ok is False
    assert "GTL" in reason and "not yet supported" in reason
    ok2, _ = _carrier_supported_or_reason("UHC")
    assert ok2 is True
