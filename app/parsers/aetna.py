"""
Aetna BOB parser (rewritten 2026-06-23 to the REAL format).

Both upload paths share core columns by NAME (so AJ's agency-wide file and the
per-agent download both parse): Medicare Number, Member ID, Member Name, Member State,
Plan ID, Coverage Period, Effective Date, Writing Agent Name, CMS New. There is NO
Term Date column. Reads .xlsx (header row 0). Extra commission/tax columns are ignored.
Names → "First MI. Last" via app.names.normalize_person_name.
"""
import pandas as pd
from app.names import normalize_person_name

REQUIRED_COLUMNS = {"Medicare Number", "Member Name", "Writing Agent Name"}


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Aetna file: {e}")
    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Aetna file missing required columns: {missing}")

    # Keep only real member rows (a Medicare Number present); drops summary/blank rows.
    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].astype(str).str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        if not mbi:
            continue
        first, _mi, last, full = normalize_person_name(_str(row, "Member Name"))
        cms_new = _str(row, "CMS New").upper()
        records.append({
            "carrier": "Aetna",
            "member_id": mbi,
            "mbi": mbi,
            "carrier_member_id": _str(row, "Member ID"),
            "first_name": first,
            "last_name": last,
            "full_name": full,
            "agent_id": _str(row, "Writing Agent Name"),   # raw name; resolved in upload
            "effective_date": _parse_date(row, "Effective Date"),
            "term_date": None,                              # Aetna BOB has no term column
            "renewal_date": _parse_date(row, "Coverage Period"),
            "state": _str(row, "Member State"),
            "plan_name": _str(row, "Plan ID"),
            "plan_type": "",
            "commission_type": "initial" if cms_new.startswith("Y") else "renewal",
            "phone": "",
            "county": "",
            "dob": None,
            "status": "active",
        })
    return records


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
