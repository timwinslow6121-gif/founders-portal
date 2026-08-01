"""
Content-based routing in app/commission/sheet_loader.py.

Carrier portals relabel their exports without changing the data: Aetna shipped
XLSX through 2026-05 then CSV in 2026-07; Devoted ships real XLSX named .xls.
The loader must route on the file's CONTENT (magic bytes), never its extension,
so a relabeled export never breaks an upload.

Grounding cases are the real 2026-07 cycle files:
  - "Founders Insurance Agency, LLC_med_comm_202607.csv"  Aetna, CSV + UTF-8 BOM
  - "20182775_Rebekah_Long_20260724 (1).xls"              Devoted, XLSX bytes
  - "CommissionData (2).xls"                              Humana, SpreadsheetML
"""
import os
import shutil
import tempfile

import pytest

from app.commission.sheet_loader import load_sheets

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "commission")


def _copy_as(src_name, dest_name):
    """Copy a fixture to a temp file under a DIFFERENT extension.

    Returns the temp path; caller is responsible for cleanup. This is how we
    simulate a carrier mislabeling its export.
    """
    src = os.path.join(FIXTURES, src_name)
    tmpdir = tempfile.mkdtemp()
    dest = os.path.join(tmpdir, dest_name)
    shutil.copyfile(src, dest)
    return dest


# --- XLSX bytes behind a wrong extension (Devoted's monthly export) ----------

def test_xlsx_bytes_named_xls_loads():
    """Real XLSX named .xls must load — openpyxl rejects on filename, so the
    loader has to bypass that check rather than trusting the extension."""
    path = _copy_as("devoted_sample.xlsx", "mislabeled.xls")
    sheets = load_sheets(path)
    assert "Agent Portion" in sheets
    assert sheets["Agent Portion"][0][17] == "Base Amount"


def test_xlsx_bytes_with_no_extension_loads():
    """Content routing must not depend on there being an extension at all."""
    path = _copy_as("devoted_sample.xlsx", "no_extension_at_all")
    sheets = load_sheets(path)
    assert "Agent Portion" in sheets


# --- CSV (Aetna 2026-07) ----------------------------------------------------

def _write_csv(body, name="aetna.csv", encoding="utf-8"):
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding=encoding, newline="") as fh:
        fh.write(body)
    return path


AETNA_CSV = (
    "Payment Date,Medicare Number,Member ID,Legacy Member ID,Member Name,"
    "Member State,Sales Event,Product,Market,Plan ID,Additional Payment Detail,"
    "Coverage Period,Effective Date,Term Date,Writing Agent NPN,"
    "Writing Agent Level,Writing Agent Name,Payee ID,Payee Level,Payee Name,"
    "Payee Amount,CMS New,Member Sig Dt,1099 Year\r\n"
    "07/01/2026,1EG4TE5MK73,M123,,\"DOE, JANE\",NC,Renewal,MAPD,NC,H3146-001,,"
    "202607,01/01/2026,,1234567,Agency,\"WINSLOW, TIMOTHY\",99,Agency,"
    "Founders Insurance Agency,57.83,N,,2026\r\n"
)


def test_csv_loads_as_sheet():
    """A plain CSV must load — it is not a zip, so the XLSX reader would raise
    'File is not a zip file' (the real 2026-07 Aetna failure)."""
    path = _write_csv(AETNA_CSV)
    sheets = load_sheets(path)
    assert len(sheets) == 1, "a CSV is a single logical sheet"
    rows = next(iter(sheets.values()))
    assert rows[0][0] == "Payment Date"
    assert rows[0][20] == "Payee Amount"
    assert len(rows) == 2


def test_csv_with_utf8_bom_has_clean_first_header():
    """Aetna's CSV carries a UTF-8 BOM. If it is not stripped the first header
    becomes '\\ufeffPayment Date' and carrier detection silently fails."""
    path = _write_csv(AETNA_CSV, name="bom.csv", encoding="utf-8-sig")
    sheets = load_sheets(path)
    rows = next(iter(sheets.values()))
    assert rows[0][0] == "Payment Date", "BOM must be stripped from first header"
    assert "﻿" not in rows[0][0]


def test_csv_named_xls_still_loads():
    """Extension must not override content: CSV bytes named .xls are still CSV."""
    path = _write_csv(AETNA_CSV, name="relabeled.xls")
    sheets = load_sheets(path)
    rows = next(iter(sheets.values()))
    assert rows[0][6] == "Sales Event"


def test_csv_preserves_embedded_commas_and_quotes():
    """Member names arrive quoted as "LAST, FIRST" — a naive split() would
    shift every downstream column and mangle the money fields."""
    path = _write_csv(AETNA_CSV, name="quoted.csv")
    sheets = load_sheets(path)
    rows = next(iter(sheets.values()))
    assert rows[1][4] == "DOE, JANE", "quoted comma must stay in one cell"
    assert rows[1][20] == "57.83", "amount must remain aligned to col20"


def test_csv_ragged_rows_do_not_lose_data():
    """Short trailing rows must not raise or truncate earlier cells."""
    body = "A,B,C\r\n1,2,3\r\n4,5\r\n"
    path = _write_csv(body, name="ragged.csv")
    rows = next(iter(load_sheets(path).values()))
    assert rows[1] == ["1", "2", "3"]
    assert rows[2][:2] == ["4", "5"]


# --- SpreadsheetML must keep working (Humana) -------------------------------

def test_spreadsheetml_still_routes_correctly():
    """Humana's HTML/XML-flavored .xls must not regress."""
    sheets = load_sheets(os.path.join(FIXTURES, "humana_sample.xls"))
    name = next(n for n in sheets if "CommissionData" in n)
    assert "WaName" in sheets[name][0]


# --- Unsupported content fails loudly ---------------------------------------

def test_unsupported_binary_raises_clear_error():
    """A PDF (the July folder contains two) must fail with a message naming the
    problem, not a confusing 'not a zip file'."""
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "statement.pdf")
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nbinary junk here")
    with pytest.raises(ValueError) as exc:
        load_sheets(path)
    msg = str(exc.value).lower()
    assert "pdf" in msg or "unsupported" in msg
