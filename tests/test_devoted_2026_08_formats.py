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


# ---------------------------------------------------------------- LEDGER PATH
# The normalizer (customer sync) and the LEDGER (money) are SEPARATE extractors.
# Fixing normalize_devoted alone left extract_lineitems_devoted falling through
# to the agency branch, which reads sheets these files do not have -> statement
# 92 imported with 0 line items, $0 ledger, and balanced=True because 0 == 0.
# A silent zero is worse than a crash: the upload looked successful.

def _split_lookup(_name, _carrier=None):
    return 0.55


def test_ledger_extracts_money_from_the_tmg_file():
    from app.commission.ledger import extract_lineitems_devoted
    drafts = extract_lineitems_devoted(_sheets(TMG), _split_lookup)
    assert drafts, "ledger extracted NOTHING — statement would import as $0"
    assert len(drafts) == 53
    assert round(sum(d.raw_amount for d in drafts), 2) == 6653.28


def test_ledger_extracts_money_from_the_new_rebekah_file():
    from app.commission.ledger import extract_lineitems_devoted
    drafts = extract_lineitems_devoted(_sheets(REB), _split_lookup)
    assert drafts, "ledger extracted NOTHING"
    assert len(drafts) == 6
    assert round(sum(d.raw_amount for d in drafts), 2) == 2602.49


def test_money_rows_total_matches_the_ledger_for_both_files():
    """The completeness invariant: the independent re-sum must equal the ledger,
    or verify_statement_balance silently passes on a dropped sheet."""
    from app.commission.ledger import extract_lineitems_devoted, money_rows_total_devoted
    for path, expected in ((TMG, 6653.28), (REB, 2602.49)):
        sheets = _sheets(path)
        drafts = extract_lineitems_devoted(sheets, _split_lookup)
        assert round(money_rows_total_devoted(sheets), 2) == expected
        assert round(sum(d.raw_amount for d in drafts), 2) == expected


def test_ledger_separates_agent_commission_from_founders_override():
    from app.commission.ledger import extract_lineitems_devoted
    drafts = extract_lineitems_devoted(_sheets(TMG), _split_lookup)
    agent = round(sum(d.raw_amount for d in drafts
                      if d.classification == "agent_commission"), 2)
    ovr = round(sum(d.raw_amount for d in drafts
                    if d.classification == "founders_override"), 2)
    cb = round(sum(d.raw_amount for d in drafts
                   if d.classification == "chargeback"), 2)
    # Negative rows are chargebacks regardless of Transaction Type, so the
    # positive Override rows ($1,917.11) and their 7 clawbacks (-$468.79) are
    # classified separately. Net Override is 1917.11 - 468.79 = 1448.32, and
    # net Commission is 6332.73 - 1127.77 = 5204.96, matching the file.
    assert ovr == 1917.11
    assert agent == 6332.73
    assert cb == -1596.56
    assert round(agent + ovr + cb, 2) == 6653.28


def test_ledger_source_refs_are_unique_and_file_scoped():
    """Devoted's replace-on-reupload deletes by source_ref prefix; a shared
    prefix across the two files would make one wipe the other."""
    from app.commission.ledger import extract_lineitems_devoted
    a = extract_lineitems_devoted(_sheets(TMG), _split_lookup)
    b = extract_lineitems_devoted(_sheets(REB), _split_lookup)
    refs_a = {d.source_ref for d in a}
    refs_b = {d.source_ref for d in b}
    assert len(refs_a) == len(a) and len(refs_b) == len(b)
    assert not (refs_a & refs_b), "the two files share source_refs — one will wipe the other"


def test_an_empty_ledger_never_reports_balanced():
    """Statement 92 imported with 0 line items, $0 ledger and balanced=True,
    because completeness compares 0 == 0. A silent zero is worse than a crash:
    the upload looked successful and $0 reached every agent. An extractor that
    finds NOTHING must fail the balance check, not pass it."""
    from app.commission.ledger import verify_statement_balance
    # Both sides zero — what actually happened: the extractor AND the re-sum
    # both read sheets the file does not have, so 0 == 0 passed.
    # A RECOGNIZED shape that yields no rows — an unrecognized one already
    # raises ValueError (fail loud), but a known shape read with the wrong
    # column names returns 0 from both sides and 0 == 0 passed.
    rep = verify_statement_balance("Devoted", [], {"Agent Report": [["Amount"]]})
    assert not rep.completeness_ok, "empty ledger reported as balanced"
