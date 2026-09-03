"""tests/test_uhc_term_reason_capture.py"""


def _uhc_sheet(term_reason):
    """Minimal UHC raw commission sheet.

    The real file is keyed by FIXED COLUMN INDEX off the 'Commission Transactions'
    sheet (see _UHC_* constants in app/commission/ledger.py): writing id 4,
    member name 7, MedicareID 8, plan type 12, action 19, amount 23. Term Reason
    is column 24 in the real statement. Build 30 columns so the indices land.
    """
    header = [""] * 30
    header[4], header[5], header[7], header[8] = ("Writing Agent ID",
                                                  "Writing Agent Name",
                                                  "Member Name", "MedicareID")
    header[11], header[12], header[19] = ("Original Effective Date", "Plan Type",
                                          "Commission Action")
    header[23], header[24], header[28] = "Commission ($)", "Term Reason", "Term Date"
    row = [""] * 30
    row[4], row[5], row[7], row[8] = "1839547", "WINSLOW, TIMOTHY J", "BOST, LINDA H.", "6MV0WK0MP06"
    row[11], row[12], row[19] = "2023-01-01", "MAPD", "Renewal"
    row[23], row[24], row[28] = "28.92", term_reason, "2026-05-31"
    return {"Commission Transactions": [header, row]}


def test_term_reason_is_captured_verbatim():
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet("Death"))
    assert any(f.term_reason_raw == "Death" for f in facts)


def test_a_blank_term_reason_is_empty_not_none():
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet(""))
    assert all(f.term_reason_raw == "" for f in facts)


def test_other_reasons_are_captured_but_are_not_deaths():
    """'Enrollment in Another Plan' is a switcher signal — stored, not acted on."""
    from app.commission.normalizers import normalize_uhc
    facts = normalize_uhc(_uhc_sheet("Enrollment in Another Plan"))
    assert any(f.term_reason_raw == "Enrollment in Another Plan" for f in facts)


def test_term_date_is_captured_so_a_death_has_a_date():
    """normalize_uhc set term_reason_raw but NOT term_date, so
    death_date_from_uhc_fact — which returns fact.term_date when the reason is
    "Death" — always returned None on the live import path. The UHC half of the
    deceased capture was dead code: the reason was read, the date never was.

    Found by Task 9's backfill, which had to bypass the normalizer and read the
    raw sheet to get a date at all.
    """
    from datetime import date
    from app.commission.normalizers import normalize_uhc
    sheet = _uhc_sheet("Death")
    sheet["Commission Transactions"][1][28] = "2026-05-31"
    facts = normalize_uhc(sheet)
    assert facts, "no facts produced"
    assert any(f.term_date == date(2026, 5, 31) for f in facts), \
        "term_date not captured — a Death row would carry no date of death"


def test_a_death_fact_yields_its_date_end_to_end():
    """The whole point: reason + date together must produce a usable death date."""
    from datetime import date
    from app.commission.normalizers import normalize_uhc
    from app.deceased import death_date_from_uhc_fact
    sheet = _uhc_sheet("Death")
    sheet["Commission Transactions"][1][28] = "2026-05-31"
    facts = normalize_uhc(sheet)
    assert any(death_date_from_uhc_fact(f) == date(2026, 5, 31) for f in facts)


def test_a_non_death_row_still_carries_its_term_date():
    """term_date is general lifecycle data, not death-specific."""
    from datetime import date
    from app.commission.normalizers import normalize_uhc
    sheet = _uhc_sheet("Member Termination")
    sheet["Commission Transactions"][1][28] = "2026-06-30"
    facts = normalize_uhc(sheet)
    assert any(f.term_date == date(2026, 6, 30) for f in facts)
