"""
UHC (UnitedHealthcare) BOB parser.

Format: XLSX
Unique ID: mbiNumber (MBI)
Active filter: export is active-only — no filter needed
Name fields: memberFirstName / memberLastName
"""

import pandas as pd
from datetime import date


REQUIRED_COLUMNS = {"mbiNumber", "memberFirstName", "memberLastName"}


def parse(filepath: str) -> list[dict]:
    """
    Parse a UHC XLSX export and return a list of normalized policy dicts.
    Raises ValueError if required columns are missing.
    """
    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read UHC file: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"UHC file missing required columns: {missing}")

    # Drop rows with no MBI
    df = df[df["mbiNumber"].notna() & (df["mbiNumber"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = row["mbiNumber"].strip().upper()
        first = _str(row, "memberFirstName")
        last = _str(row, "memberLastName")

        records.append({
            "carrier": "UHC",
            "member_id": mbi,          # MBI is primary key for UHC
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "planName"),
            "plan_type": _str(row, "planType"),
            "effective_date": _parse_date(row, "effectiveDate"),
            "term_date": _parse_date(row, "termDate"),
            "dob": _parse_date(row, "memberDOB"),
            "phone": _str(row, "memberPhone"),
            "county": _str(row, "county"),
            "agent_id": _str(row, "agentId"),
            "status": "active",
        })

    return records


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if pd.isna(val):
        return ""
    return str(val).strip()


def _parse_date(row, col: str):
    val = row.get(col, "")
    if pd.isna(val) or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
