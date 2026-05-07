"""
Healthspring (Cigna) BOB parser.

Supports two export formats from the Healthspring agent portal:

  XLSX format: 12-row preamble before headers (title, filters, blanks).
               Parsed with pandas read_excel(header=12).

  XLS format:  HTML disguised as .xls — no preamble, headers on row 0.
               Parsed with pandas read_html().

Both formats share identical column names. Key columns:
  First Name, Last Name, Medicare Number (MBI), Member ID,
  Effective Date, Disenroll Effective Date, Date of Birth,
  Phone Number, Residential Address/City/State/Zip, Status, Product, Agent NPN
"""
import pandas as pd
from io import StringIO

REQUIRED_COLUMNS = {"First Name", "Last Name", "Medicare Number"}
ACTIVE_STATUSES = {"enrolled", "pending-future"}


def parse(filepath: str) -> list[dict]:
    try:
        df = _read_file(filepath)
    except Exception as e:
        raise ValueError(f"Could not read Healthspring file: {e}")

    df.columns = df.columns.str.strip()
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Healthspring file missing required columns: {missing}")

    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].str.strip().str.upper() != "NAN")].copy()
    df = df[df["Medicare Number"].str.strip() != ""].copy()

    records = []
    for _, row in df.iterrows():
        mbi       = _str(row, "Medicare Number").upper()
        if not mbi:
            continue
        first     = _str(row, "First Name").title()
        last      = _str(row, "Last Name").title()
        status_raw = _str(row, "Status").lower()
        term_date  = _parse_date(row, "Disenroll Effective Date")

        records.append({
            "carrier":        "Healthspring",
            "member_id":      _str(row, "Member ID") or mbi,
            "mbi":            mbi,
            "first_name":     first,
            "last_name":      last,
            "full_name":      f"{first} {last}".strip(),
            "plan_name":      _str(row, "Product"),
            "plan_type":      _str(row, "Product Type") if "Product Type" in df.columns else "MAPD",
            "effective_date": _parse_date(row, "Effective Date"),
            "term_date":      term_date,
            "renewal_date":   None,
            "dob":            _parse_date(row, "Date of Birth"),
            "phone":          _str(row, "Phone Number"),
            "county":         "",
            "address1":       _str(row, "Residential Address").title(),
            "city":           _str(row, "Residential City").title(),
            "state":          _str(row, "Residential State").upper(),
            "zip_code":       _str(row, "Residential Zip Code"),
            "agent_id":       _str(row, "Agent NPN") if "Agent NPN" in df.columns else "",
            "status":         "active" if status_raw in ACTIVE_STATUSES else "termed",
        })
    return records


def _read_file(filepath: str) -> pd.DataFrame:
    """Auto-detect XLSX-with-preamble vs HTML-disguised-as-XLS."""
    with open(filepath, "rb") as f:
        header_bytes = f.read(6)

    is_html = b"<" in header_bytes[:2]

    if is_html:
        with open(filepath, "r", encoding="ISO-8859-1", errors="replace") as f:
            content = f.read()
        tables = pd.read_html(StringIO(content), header=0)
        if not tables:
            raise ValueError("No tables found in Healthspring HTML export")
        return tables[0].astype(str)
    else:
        return pd.read_excel(filepath, header=12, dtype=str)


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if pd.isna(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or pd.isna(val) or str(val).strip() in ("", "nan", "None", "NaT"):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
