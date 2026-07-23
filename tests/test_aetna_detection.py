import os
import pytest
from app.upload import _detect_carrier

BASE = "docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs"
AGENCY = f"{BASE}/Aetna - April - Founders Book of Business.xlsx"
AGENT = f"{BASE}/Aetna - Tim Winslow April Book of Business.xlsx"


@pytest.mark.skipif(not os.path.exists(AGENCY), reason="Aetna agency fixture absent")
def test_detects_aetna_agency_file():
    """Test that the agency-level Aetna BOB file is correctly identified."""
    result = _detect_carrier(AGENCY, os.path.basename(AGENCY))
    assert result == "Aetna", f"Expected 'Aetna' but got '{result}'"


@pytest.mark.skipif(not os.path.exists(AGENT), reason="Aetna agent fixture absent")
def test_detects_aetna_agent_file():
    """Test that the per-agent Aetna BOB file is correctly identified."""
    result = _detect_carrier(AGENT, os.path.basename(AGENT))
    assert result == "Aetna", f"Expected 'Aetna' but got '{result}'"


@pytest.mark.skipif(
    not (os.path.exists(AGENCY) and os.path.exists(AGENT)),
    reason="Aetna fixtures absent",
)
def test_detects_both_aetna_files():
    """Test that both Aetna BOB file formats are correctly identified."""
    assert _detect_carrier(AGENCY, os.path.basename(AGENCY)) == "Aetna"
    assert _detect_carrier(AGENT, os.path.basename(AGENT)) == "Aetna"


def test_detect_carrier_finds_data_on_non_first_sheet(tmp_path):
    """A BOB with a pivot 'Sheet1' in FRONT of the real data sheet (Devoted's
    'application_status_report_2026_' shape) must still detect the carrier — the
    fingerprint headers are on the 2nd sheet, not wb.active."""
    import openpyxl
    from app.upload import _detect_carrier
    p = tmp_path / "Devoted Book of business.xlsx"
    wb = openpyxl.Workbook()
    junk = wb.active
    junk.title = "Sheet1"
    junk.append(["2025", "2025 Total", "2026"])          # pivot junk, no fingerprint
    junk.append(["1", "2", "3"])
    data = wb.create_sheet("application_status_report_2026_")
    data.append(["Application Status Report Agent Name",
                 "Application Status Report Full Name",
                 "Application Status Report Mbi"])
    data.append(["Justin Basinger", "Praize Medley", "2T74G35WQ90"])
    wb.save(p)
    assert _detect_carrier(str(p), "Devoted Book of business.xlsx") == "Devoted"
