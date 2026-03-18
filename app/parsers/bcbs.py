"""
BCBS NC BOB parser.

Format: CSV
Unique ID: Medicare Number (MBI)
Active filter: term_date > today  (export includes historical termed records — MUST filter)
Name fields: First Name / Last Name
"""

import pandas as pd
from datetime import date


REQUIRED_COLUMNS = {"First Name", "Last Name", "Medicare Number"}


def parse(filepath: str) -> list[dict]:
    """
    Parse a BCBS NC CSV export and return a list of normalized policy dicts.
    Filters out records where term date is in the past (historical termed members).
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read BCBS file: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"BCBS file missing required columns: {missing}")

    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].str.strip() != "")]
    df = df.copy()

    today = date.today()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        first = _str(row, "First Name")
        last = _str(row, "Last Name")

        term_date = _parse_date(row, "Term Date") or _parse_date(row, "TermDate") or _parse_date(row, "Termination Date")

        # Filter: skip records where term date is in the past
        # Null term_date means no term set — keep it (active)
        if term_date is not None and term_date < today:
            continue

        records.append({
            "carrier": "BCBS",
            "member_id": mbi,
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "Plan Name") or _str(row, "PlanName"),
            "plan_type": _str(row, "Plan Type") or _str(row, "PlanType"),
            "effective_date": _parse_date(row, "Effective Date") or _parse_date(row, "EffectiveDate"),
            "term_date": term_date,
            "dob": _parse_date(row, "Date of Birth") or _parse_date(row, "DOB"),
            "phone": _str(row, "Phone") or _str(row, "Phone Number"),
            "county": _str(row, "County"),
            "agent_id": _str(row, "Agent ID") or _str(row, "AgentID"),
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
