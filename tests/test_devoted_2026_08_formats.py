"""
tests/test_devoted_2026_08_formats.py

Devoted's August 2026 files are two BRAND-NEW shapes. AJ's upload failed with
"Could not detect the carrier from this file's headers" because the detector
fingerprints 'member hicn' / 'agent npn' and neither column exists any more.

  Rebekah_Long_Commissions_August_2026.xlsx
      was  Summary / Detail          with 'Member HICN', 'Agent NPN'
      now  Transactions / Statement Summary with 'MBI', 'Agent ID', 'Contract'

  Commission-Statement-2026-08-11.xlsx
      NOT a Devoted export at all -- a Tidewater Management Group (TMG) FMO
      statement, one 'Agent Report' sheet, with a literal Carrier column
      reading DEVOTEDHEALTH. TMG could route other carriers through the same
      format, so it gets its own normalizer that reads that column rather than
      a Devoted branch that assumes the carrier.

VERIFIED TOTALS (tied to each file's own summary before any code was written):
  TMG      53 data rows = $6,653.28  == the file's 'Total Amount:' AND
           'Payment Amount:' rows, which must NOT be imported ($13,306.56 of
           summary lines, 67% of the raw sum -- importing them would inflate
           the statement enormously).
           Commission $5,204.96 (agent) + Override $1,448.32 (Founders).
           12 chargebacks = -$1,596.56.
  Rebekah  6 rows = $2,602.49; minus the -$168.74 balance adjustment that is
           $2,433.75 == sum of 'Statement Total' in Statement Summary.
"""
import os

import pytest

D = "docs/Commission DL/_organized/2026-08_cycle/Devoted"
TMG = os.path.join(D, "Commission-Statement-2026-08-11.xlsx")
REB = os.path.join(D, "Rebekah_Long_Commissions_August_2026.xlsx")

pytestmark = pytest.mark.skipif(
    not (os.path.exists(TMG) and os.path.exists(REB)),
    reason="August Devoted files not present")


def _sheets(path):
    from app.commission.routes import load_sheets_from_bytes
    return load_sheets_from_bytes(open(path, "rb").read(), os.path.basename(path))


def _total(facts):
    return round(sum(f.amount for f in facts), 2)


# ---------------------------------------------------------------- detection

def test_both_august_files_detect_a_carrier():
    """The reported failure: neither file detected, so nothing imported."""
    from app.commission.routes import _detect_carrier_from_sheets
    assert _detect_carrier_from_sheets(_sheets(REB)) == "Devoted"
    assert _detect_carrier_from_sheets(_sheets(TMG)) == "Devoted"


def test_detected_carrier_is_supported():
    from app.commission.routes import _detect_carrier_from_sheets
    from app.commission.normalizers import NORMALIZERS
    for p in (REB, TMG):
        assert _detect_carrier_from_sheets(_sheets(p)) in NORMALIZERS


# ---------------------------------------------------------------- Rebekah

def test_rebekah_new_layout_parses_every_row():
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(REB))
    assert len(facts) == 6
    assert _total(facts) == 2602.49


def test_rebekah_rows_carry_identity_and_dates():
    from app.commission.normalizers import normalize_devoted
    facts = {f.full_name: f for f in normalize_devoted(_sheets(REB))}
    roseman = next(f for n, f in facts.items() if "Roseman" in n)
    assert roseman.mbi == "5GQ2KF8PC21"
    assert roseman.amount == 607.25
    assert roseman.plan_contract == "H9700"
    assert roseman.writing_agent_raw == "Rebekah Long"


def test_rebekah_classifies_new_vs_renewal():
    from app.commission.member_fact import RowClass
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(REB))
    kinds = {f.row_class for f in facts}
    assert RowClass.ENROLLMENT in kinds and RowClass.RENEWAL in kinds


# ---------------------------------------------------------------- TMG

def test_tmg_excludes_the_summary_rows():
    """The two 'Total Amount:' / 'Payment Amount:' rows are $13,306.56 of
    summary -- importing them would more than double the statement."""
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(TMG))
    assert len(facts) == 53
    assert _total(facts) == 6653.28


def test_tmg_separates_agent_commission_from_founders_override():
    """Transaction Type already splits the two — treating every row as agent
    commission would double-count Founders' share."""
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(TMG))
    agent = round(sum(f.amount for f in facts if not f.is_agency_share), 2)
    agency = round(sum(f.amount for f in facts if f.is_agency_share), 2)
    assert agent == 5204.96
    assert agency == 1448.32
    assert round(agent + agency, 2) == 6653.28


def test_tmg_keeps_chargebacks_signed():
    from app.commission.member_fact import RowClass
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(TMG))
    negs = [f for f in facts if f.amount < 0]
    assert len(negs) == 12
    assert round(sum(f.amount for f in negs), 2) == -1596.56
    assert all(f.row_class == RowClass.CHARGEBACK for f in negs)


def test_tmg_carries_the_writing_agent():
    from app.commission.normalizers import normalize_devoted
    facts = normalize_devoted(_sheets(TMG))
    writers = {f.writing_agent_raw for f in facts if f.writing_agent_raw}
    assert "Brian Freeman" in writers
    assert "Michael Lauzurique" in writers


def test_tmg_source_refs_are_unique():
    """source_ref is the idempotency key for re-upload — a collision silently
    drops rows."""
    from app.commission.normalizers import normalize_devoted
    refs = [f.source_ref for f in normalize_devoted(_sheets(TMG))]
    assert len(refs) == len(set(refs))


def test_old_devoted_shapes_still_parse():
    """The July files must keep working — a re-import of history is still
    outstanding for the provenance backfill."""
    from app.commission.normalizers import normalize_devoted
    old = ("docs/Commission DL/_organized/2026-07_cycle/Founders_Commission_July_2026/"
           "Founders Devoted June 2026 TM July 2026.xlsx")
    if not os.path.exists(old):
        pytest.skip("July agency file not present")
    facts = normalize_devoted(_sheets(old))
    assert facts and all(f.source_ref.startswith("devoted::agency::") for f in facts)
