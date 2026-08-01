"""
app/commission/sheet_loader.py

Loads a commission file into {sheet_name: list[list[cell]]} regardless of the
formats AJ's carriers ship:
  - true XLSX (most carriers)
  - .xls extension that is actually XLSX (PK/zip bytes) — Devoted per-agent
  - SpreadsheetML 2003 XML with a broken `<xml version>` first line — Humana
  - plain CSV (Aetna switched XLSX → CSV between 2026-05 and 2026-07)

ROUTING IS BY CONTENT, NEVER BY EXTENSION. Carrier portals relabel their
exports without changing the data — the same Aetna report arrived as .xlsx in
2026-05 and .csv in 2026-07, and Devoted ships real XLSX named .xls every
month. Sniffing magic bytes is the only thing that survives that churn.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md
"Per-carrier reference".
"""
import csv
import io
import re
import xml.etree.ElementTree as ET

import openpyxl


def _sniff(path, n=8):
    """Return the first n bytes of the file (used for magic-byte routing)."""
    with open(path, "rb") as fh:
        return fh.read(n)


def _load_xlsx(path):
    """Load an XLSX file into {sheet_name: list[list[cell]]}.

    Opened as a file HANDLE rather than a path on purpose: openpyxl rejects a
    path ending in .xls on the filename alone, even when the bytes are a valid
    XLSX. Handing it a stream bypasses that check, which is what lets Devoted's
    mislabeled per-agent export load without being renamed first.
    """
    with open(path, "rb") as fh:
        data = io.BytesIO(fh.read())
    wb = openpyxl.load_workbook(data, read_only=True, data_only=True)
    out = {}
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([("" if c is None else c) for c in row])
        out[ws.title] = rows
    wb.close()
    return out


_SS = "urn:schemas-microsoft-com:office:spreadsheet"


def _load_spreadsheetml(path):
    """Load Humana SpreadsheetML 2003 XML into {sheet_name: list[list[cell]]}. Assumes dense rows (no ss:Index); raises ValueError if a file uses ss:Index."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    # Fix the broken first line `<xml version>` → strip it; keep <Workbook ...>
    raw = re.sub(r"^\s*<xml[^>]*>\s*", "", raw, count=1)
    root = ET.fromstring(raw)
    out = {}
    for ws in root.iter("{%s}Worksheet" % _SS):
        name = ws.get("{%s}Name" % _SS)
        table = ws.find("{%s}Table" % _SS)
        if table is None:
            continue
        rows = []
        for r in table.findall("{%s}Row" % _SS):
            cells = []
            for c in r.findall("{%s}Cell" % _SS):
                if c.get("{%s}Index" % _SS) is not None:
                    raise ValueError(
                        "SpreadsheetML ss:Index (sparse columns) is not supported by "
                        "this loader; a carrier file used it. Column alignment would be "
                        "wrong. Add ss:Index handling before parsing this file."
                    )
                d = c.find("{%s}Data" % _SS)
                cells.append("" if d is None or d.text is None else d.text)
            rows.append(cells)
        out[name] = rows
    return out


def _load_csv(path):
    """Load a delimited text file into {sheet_name: list[list[cell]]}.

    Read with utf-8-sig so a Microsoft UTF-8 BOM is stripped. Aetna's export
    carries one; left in place it fuses onto the first header ('﻿Payment
    Date'), and since carriers are identified by header text that alone is
    enough to make detection fail.

    csv.Sniffer picks the delimiter so a tab- or semicolon-separated export
    still lands in the right columns. Every cell stays a string — parsing of
    dates and money belongs to the per-carrier normalizers, not here.
    """
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(64 * 1024)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel  # single-column or ambiguous → comma default
        rows = [list(r) for r in csv.reader(fh, dialect)]

    # Drop trailing blank lines; keep interior blanks (carriers use them as
    # section separators and normalizers rely on the row positions).
    while rows and not any(str(c).strip() for c in rows[-1]):
        rows.pop()

    # Pad every row to the widest row, matching _load_xlsx which yields
    # rectangular sheets. Normalizers read by fixed column index, so a short
    # trailing row must not IndexError on a carrier whose guard is missing.
    if rows:
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]

    return {"Sheet1": rows}


#: Magic-byte signatures that are definitively NOT spreadsheets or text. These
#: must be rejected before the text fallback — several (notably %PDF) contain
#: no null bytes early on and would otherwise look like parseable text.
_BINARY_SIGNATURES = (
    b"%PDF",              # PDF — carrier statements arrive as PDFs alongside data
    b"\xd0\xcf\x11\xe0",  # OLE2 — genuine legacy binary .xls (needs xlrd, unsupported)
    b"\x89PNG",           # PNG
    b"\xff\xd8\xff",      # JPEG
    b"GIF8",              # GIF
    b"Rar!",              # RAR
    b"\x1f\x8b",          # gzip
)


def _KNOWN_BINARY(head):
    """True if the leading bytes match a known non-spreadsheet binary format."""
    return any(head.startswith(sig) for sig in _BINARY_SIGNATURES)


def _describe_bytes(head):
    """Best-effort name for an unsupported file, for the error message."""
    if head.startswith(b"%PDF"):
        return "a PDF"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        # OLE2 compound document = genuine legacy .xls (pre-2007 binary)
        return "a legacy binary .xls (Excel 97-2003)"
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff"):
        return "an image"
    return "an unrecognized binary format"


def _looks_like_text(sample):
    """True if the sample looks like decodable text rather than binary.

    Judged on the ratio of printable bytes, not on decodability: a latin-1 CSV
    fails utf-8 decoding but is still text, while a compressed archive often
    decodes without raising. Anything unrecognized must fail loudly rather than
    be parsed into a one-row grid of garbage — this feeds a money path.
    """
    if not sample:
        return False
    if b"\x00" in sample:
        return False
    printable = sum(
        1 for b in sample
        if b in (9, 10, 13) or 32 <= b < 127 or b >= 128
    )
    return printable / len(sample) > 0.9


def load_sheets(path):
    """Return {sheet_name: list[list[cell]]} for any supported commission file.

    Routes on CONTENT, not extension — see the module docstring. Order matters:
    zip is checked first (XLSX is a zip), then markup, then text/CSV.
    """
    # Sniff a generous window, not just the magic bytes: the markup test below
    # has to survive leading whitespace or a BOM from a carrier that starts
    # pretty-printing its XML, and the text test needs enough bytes to judge.
    head = _sniff(path, 4096)

    # 1. ZIP magic → XLSX, whatever the file is named (.xls, .xlsx, no extension)
    if head[:2] == b"PK":
        return _load_xlsx(path)

    # 2. Markup → SpreadsheetML 2003 / HTML-disguised-as-xls (Humana).
    #    Tolerates a UTF-8 BOM and arbitrary leading whitespace.
    if head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        return _load_spreadsheetml(path)

    # 3. Text → delimited (Aetna CSV). Checked AFTER markup so an XML file is
    #    never parsed as a one-column CSV, and it is the only branch that
    #    accepts an unrecognized file — so it must be conservative.
    if not _KNOWN_BINARY(head) and _looks_like_text(head):
        return _load_csv(path)

    # 4. Anything else → fail loudly, naming what was found, so the upload UI
    #    can tell AJ what is wrong instead of "File is not a zip file".
    raise ValueError(
        f"Unsupported commission file format: this looks like "
        f"{_describe_bytes(head)}, not a spreadsheet or CSV. Nothing was imported."
    )
