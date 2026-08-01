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


# --- Route-level: the loader fix must actually reach the upload path --------
#
# The loader tests above pass against load_sheets() in isolation. That is not
# enough: _process_one_file() previously gated the normalized pipeline on
# `not filename.endswith(".csv")`, so a correct loader was never consulted for
# Aetna's CSV and the file imported via the legacy path with NO ledger rows.
# These tests pin the route behavior so that gap cannot reopen.

REAL_JULY = os.path.join(
    os.path.dirname(__file__), "..", "docs", "Commission DL", "_organized",
    "2026-07_cycle", "Founders_Commission_July_2026",
)
AETNA_CSV_FILE = os.path.join(REAL_JULY, "Founders Insurance Agency, LLC_med_comm_202607.csv")


@pytest.fixture
def app_ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T")
        db.session.add(ag)
        db.session.flush()
        yield app, ag.id
        db.session.remove()
        db.drop_all()


def test_csv_upload_reaches_normalized_pipeline(app_ctx):
    """A .csv upload must reach _ingest_normalized_upload — the ledger path.

    _process_one_file() used to skip the content probe for any .csv, so Aetna
    imported via the legacy path and wrote NO CommissionLineItem rows. Asserting
    the ingest function is actually CALLED is what pins that gate open; checking
    only that the carrier is detectable would pass either way.
    """
    from unittest.mock import patch
    from app.commission.routes import _process_one_file
    app, agency_id = app_ctx
    body = AETNA_CSV.encode("utf-8")

    sentinel = {"filename": "x", "ok": True, "error": None, "fix": None}
    with app.test_request_context():
        with patch("app.commission.routes._ingest_normalized_upload",
                   return_value=sentinel) as ingest:
            _process_one_file(
                file_bytes=body, filename="aetna_export.csv",
                statement_month="2026-07", agency_id=agency_id,
                actor=None, replace=False,
            )
    assert ingest.called, (
        "a .csv must reach the normalized ingest; if this fails the CSV is "
        "falling through to the legacy path and writing no ledger rows"
    )
    assert ingest.call_args[0][0] == "Aetna"


@pytest.mark.skipif(not os.path.exists(AETNA_CSV_FILE),
                    reason="real 2026-07 Aetna CSV not present")
def test_real_aetna_csv_detects_through_upload_path(app_ctx):
    """The actual file that failed in production, through the byte path."""
    from app.commission.routes import load_sheets_from_bytes, _detect_carrier_from_sheets
    with open(AETNA_CSV_FILE, "rb") as fh:
        body = fh.read()
    sheets = load_sheets_from_bytes(body, os.path.basename(AETNA_CSV_FILE))
    assert _detect_carrier_from_sheets(sheets) == "Aetna"


def test_unsupported_file_error_surfaces_to_uploader(app_ctx):
    """A PDF must return the loader's descriptive message, NOT the legacy
    path's 'Could not read file: File is not a zip file'."""
    from app.commission.routes import _process_one_file
    app, agency_id = app_ctx
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\ntrailing junk"
    with app.test_request_context():
        res = _process_one_file(
            file_bytes=pdf, filename="statement.pdf", statement_month="2026-07",
            agency_id=agency_id, actor=None, replace=False,
        )
    assert res["ok"] is False
    msg = res["error"].lower()
    assert "pdf" in msg, f"expected the PDF to be named, got: {res['error']}"
    assert "not a zip file" not in msg, "legacy error must not leak to the UI"
