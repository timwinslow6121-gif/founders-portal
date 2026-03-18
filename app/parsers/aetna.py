"""
Aetna BOB parser.

Format: CSV
Unique ID: Medicare Number (MBI)
Active filter: Member Status == "A"  (must filter — export includes inactive)
Name fields: First Name / Last Name
"""

import pandas as pd


REQUIRED_COLUMNS = {"First Name", "Last Name", "Medicare Number"}


def parse(filepath: str) -> list[dict]:
    """
    Parse an Aetna CSV export and return a list of normalized policy dicts.
    Filters to Member Status == 'A' (active) only.
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Aetna file: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Aetna file missing required columns: {missing}")

    # Filter to active members only
    if "Member Status" in df.columns:
        df = df[df["Member Status"].str.strip().str.upper() == "A"]
    elif "MemberStatus" in df.columns:
        df = df[df["MemberStatus"].str.strip().str.upper() == "A"]

    df = df[df["Medicare Number"].notna() & (df["Medicare Number"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        first = _str(row, "First Name")
        last = _str(row, "Last Name")

        records.append({
            "carrier": "Aetna",
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
