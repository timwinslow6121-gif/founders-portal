"""
Healthspring (Cigna) BOB parser.

Format: .xls extension BUT the file is actually HTML — NOT a real Excel binary.
        Must parse as HTML, not with openpyxl/xlrd.
Unique ID: Medicare Number (MBI)
Active filter: Status == "Enrolled"
Name fields: First Name / Last Name
"""

import pandas as pd
from io import StringIO


REQUIRED_COLUMNS = {"First Name", "Last Name", "Medicare Number"}


def parse(filepath: str) -> list[dict]:
    """
    Parse a Healthspring .xls export (which is actually HTML) and return
    a list of normalized policy dicts. Filters to Status == 'Enrolled'.

    IMPORTANT: This file has an .xls extension but is HTML internally.
    We read the raw bytes to detect this and route to the correct parser.
    """
    # Detect whether file is HTML or true XLS/XLSX
    with open(filepath, "rb") as f:
        header = f.read(6)

    is_html = header[:5] in (b"<html", b"<HTML", b"<!DOC", b"<?xml") or header[:3] == b"\xef\xbb\xbf"

    if is_html or _sniff_html(filepath):
        df = _parse_as_html(filepath)
    else:
        # Attempt genuine Excel parse as a fallback
        try:
            df = pd.read_excel(filepath, dtype=str)
        except Exception as e:
            raise ValueError(f"Healthspring file could not be parsed as Excel or HTML: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Healthspring file missing required columns: {missing}")

    # Filter to enrolled members only
    status_col = next((c for c in df.columns if c.lower() in ("status", "member status", "enrollment status")), None)
    if status_col:
        df = df[df[status_col].str.strip().str.lower() == "enrolled"]

    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        first = _str(row, "First Name")
        last = _str(row, "Last Name")

        records.append({
            "carrier": "Healthspring",
            "member_id": mbi,
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "Plan Name") or _str(row, "PlanName"),
            "plan_type": _str(row, "Plan Type") or _str(row, "PlanType"),
            "effective_date": _parse_date(row, "Effective Date") or _parse_date(row, "EffectiveDate"),
            "term_date": _parse_date(row, "Term Date") or _parse_date(row, "TermDate"),
            "dob": _parse_date(row, "Date of Birth") or _parse_date(row, "DOB"),
            "phone": _str(row, "Phone") or _str(row, "Phone Number"),
            "county": _str(row, "County"),
            "agent_id": _str(row, "Agent ID") or _str(row, "AgentID"),
            "status": "active",
        })

    return records


def _sniff_html(filepath: str) -> bool:
    """Read first 512 bytes as text to detect HTML markers."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            chunk = f.read(512).lower()
        return "<html" in chunk or "<table" in chunk or "<!doctype" in chunk
    except Exception:
        return False


def _parse_as_html(filepath: str) -> pd.DataFrame:
    """Parse an HTML file as a pandas DataFrame using the first table found."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    try:
        tables = pd.read_html(StringIO(content), header=0)
    except Exception as e:
        raise ValueError(f"Healthspring: failed to parse HTML table: {e}")

    if not tables:
        raise ValueError("Healthspring: no tables found in HTML file")

    # Pick the table with the most columns — likely the data table
    df = max(tables, key=lambda t: len(t.columns))
    return df.astype(str)


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or (isinstance(val, float) and pd.isna(val)) or str(val).strip() in ("", "nan", "None", "NaT"):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
