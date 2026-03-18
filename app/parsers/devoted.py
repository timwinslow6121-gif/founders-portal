"""
Devoted Health BOB parser.

Format: CSV (raw API dump, snake_case column names)
Unique ID: member_id (UUID — NOT an MBI)
Active filter: status == "ENROLLED"
Name fields: first_name / last_name
"""

import pandas as pd


REQUIRED_COLUMNS = {"member_id", "first_name", "last_name"}


def parse(filepath: str) -> list[dict]:
    """
    Parse a Devoted Health CSV export and return a list of normalized policy dicts.
    Filters to status == 'ENROLLED' only.
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Devoted file: {e}")

    # Devoted exports are snake_case — normalize headers defensively
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Devoted file missing required columns: {missing}")

    # Filter to enrolled members only
    if "status" in df.columns:
        df = df[df["status"].str.strip().str.upper() == "ENROLLED"]

    df = df[df["member_id"].notna() & (df["member_id"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        member_id = _str(row, "member_id")
        first = _str(row, "first_name")
        last = _str(row, "last_name")

        # Devoted may include Medicare ID separately
        mbi = _str(row, "medicare_id") or _str(row, "mbi") or ""

        records.append({
            "carrier": "Devoted",
            "member_id": member_id,    # UUID — not MBI
            "mbi": mbi.upper() if mbi else "",
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "plan_name"),
            "plan_type": _str(row, "plan_type"),
            "effective_date": _parse_date(row, "effective_date"),
            "term_date": _parse_date(row, "term_date") or _parse_date(row, "disenrollment_date"),
            "dob": _parse_date(row, "date_of_birth") or _parse_date(row, "dob"),
            "phone": _str(row, "phone") or _str(row, "phone_number"),
            "county": _str(row, "county"),
            "agent_id": _str(row, "agent_id") or _str(row, "writing_agent_id"),
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
