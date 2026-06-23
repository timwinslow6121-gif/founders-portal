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
