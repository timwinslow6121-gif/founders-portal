"""
UHC (UnitedHealthcare) BOB parser.
Header is on row index 2 — file has a 2-row UHC preamble before the data.
Confirmed columns from live file March 2026.
"""
import pandas as pd

REQUIRED_COLUMNS = {"mbiNumber", "memberFirstName", "memberLastName"}
UHC_NO_TERM_SENTINEL = "2300-01-01"


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_excel(filepath, header=2, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read UHC file: {e}")

    df.columns = df.columns.str.strip()
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"UHC file missing required columns: {missing}")

    df = df[df["mbiNumber"].notna() & (df["mbiNumber"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "mbiNumber").upper()
        first = _str(row, "memberFirstName")
        last = _str(row, "memberLastName")
        raw_term = _str(row, "policyTermDate")
        term_date = None
        if raw_term and raw_term != UHC_NO_TERM_SENTINEL:
            term_date = _parse_date(row, "policyTermDate")
        records.append({
            "carrier": "UHC",
            "member_id": mbi,
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "planName"),
            "plan_type": _str(row, "product"),
            "effective_date": _parse_date(row, "policyEffectiveDate"),
            "term_date": term_date,
            "dob": _parse_date(row, "dateOfBirth"),
            "phone": _str(row, "memberPhone"),
            "county": _str(row, "memberCounty"),
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
