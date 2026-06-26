"""Test scripts/audit_integrity.py CLI report builder."""
import sys
import pathlib


def test_build_report_shape(app, db_session):
    """Test that build_report() returns the expected structure."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import audit_integrity
    with app.app_context():
        report = audit_integrity.build_report()
    assert isinstance(report, list) and report
    row = report[0]
    for field in ("key", "domain", "severity", "count", "baseline", "delta"):
        assert field in row, f"Missing field: {field}"
    # Check that sample and description are present too (not just the minimal fields)
    assert "sample" in row
    assert "description" in row


def test_build_report_delta_calculation(app, db_session):
    """Test that delta (count - baseline) is calculated correctly."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    import audit_integrity
    with app.app_context():
        report = audit_integrity.build_report()
    # All counts should match actual data (0 in empty test DB)
    for row in report:
        assert row["delta"] == row["count"] - row["baseline"]
