"""
Healthspring (Cigna) BOB parser.

File format: XLSX downloaded from Healthspring/Cigna agent portal.
Rows 0-11: preamble (title, filters, blank rows). Row 12: column headers. Row 13+: data.
Last row is a "Total / Count" summary row — filtered out by MBI check.

Key columns (by name via pandas):
  First Name, Last Name, Medicare Number (MBI), Member ID,
  Effective Date, Disenroll Effective Date, Date of Birth,
  Phone Number, Residential Address, Residential City,
  Residential State, Residential Zip Code, Status, Product, Agent NPN
"""
import pandas as pd

REQUIRED_COLUMNS = {"First Name", "Last Name", "Medicare Number"}


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_excel(filepath, header=12, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Healthspring file: {e}")

    df.columns = df.columns.str.strip()
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Healthspring file missing required columns: {missing}")

    # Filter to rows with a real MBI (drops totals row and blanks)
    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].str.strip() != "")].copy()

    # Active = Enrolled or Pending-Future; termed = Disenrolled
    status_col = "Status"
    active_statuses = {"enrolled", "pending-future"}

    records = []
    for _, row in df.iterrows():
        mbi    = _str(row, "Medicare Number").upper()
        first  = _str(row, "First Name").title()
        last   = _str(row, "Last Name").title()
        status_raw = _str(row, status_col).lower()
        is_active  = status_raw in active_statuses

        term_date = _parse_date(row, "Disenroll Effective Date")

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
            "status":         "active" if is_active else "termed",
        })
    return records


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
