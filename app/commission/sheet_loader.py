"""
app/commission/sheet_loader.py

Loads a commission file into {sheet_name: list[list[cell]]} regardless of the
three real formats AJ's carriers ship:
  - true XLSX (most carriers)
  - .xls extension that is actually XLSX (PK/zip bytes) — Devoted per-agent
  - SpreadsheetML 2003 XML with a broken `<xml version>` first line — Humana

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md
"Per-carrier reference".
"""
import re
import xml.etree.ElementTree as ET

import openpyxl


def _looks_like_zip(path):
    """Return True if the file starts with the PK header (ZIP/XLSX magic bytes)."""
    with open(path, "rb") as fh:
        return fh.read(2) == b"PK"


def _load_xlsx(path):
    """Load an XLSX file via openpyxl into {sheet_name: list[list[cell]]}."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
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


def load_sheets(path):
    """Return {sheet_name: list[list[cell]]} for any supported commission file."""
    if path.lower().endswith(".xlsx") or _looks_like_zip(path):
        return _load_xlsx(path)
    # .xls that is not a zip → SpreadsheetML XML (Humana)
    return _load_spreadsheetml(path)
