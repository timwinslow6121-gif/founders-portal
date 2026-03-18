"""
BCBS NC BOB parser.

Format: CSV — includes MA, Medicare Supplement, and Dental on same export
Unique ID: Medicare Number (MBI) for MA; BCBSNC Member Number for Supplement/Dental
Active filter: Termination Date > today AND not a sentinel date (12/31/2199)
Name fields: First Name / Last Name

Confirmed columns from live file March 2026:
First Name, Last Name, Date Of Birth, Home Phone, County, Medicare Number,
Effective Date, Termination Date, Plan, Plan Type, Line Of Business,
Producer ID, BCBSNC Member Number

Plan Type values: Medicare Advantage, Medicare Supplement, Dental
Line Of Business: IBMA, IBMS, IDTL

IMPORTANT: Termination Date for Medicare Supplement rows is the renewal/
anniversary date, NOT a real disenrollment. These should never appear in
the upcoming terminations list. We flag them with is_renewal=True.
"""

import pandas as pd
from datetime import date

REQUIRED_COLUMNS = {"First Name", "Last Name"}
BCBS_SENTINEL_DATES = {"12/31/2199", "12/31/9999", "01/01/9999"}


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read BCBS file: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"BCBS file missing required columns: {missing}")

    today = date.today()
    records = []

    for _, row in df.iterrows():
        first = _str(row, "First Name")
        last = _str(row, "Last Name")
        if not first and not last:
            continue

        plan_type = _str(row, "Plan Type")
        lob = _str(row, "Line Of Business")

        # Use MBI for MA, BCBSNC Member Number for Supplement/Dental
        mbi = _str(row, "Medicare Number").upper()
        member_num = _str(row, "BCBSNC Member Number")
        member_id = mbi if mbi else member_num
        if not member_id:
            continue

        # Parse term date
        raw_term = _str(row, "Termination Date")
        is_sentinel = raw_term in BCBS_SENTINEL_DATES
        term_date = None if is_sentinel else _parse_date(row, "Termination Date")

        # Skip records that have already termed (real past term dates only)
        # Supplement renewal dates in the past just mean it renewed — keep the record
        is_supplement = plan_type.lower() in ("medicare supplement",) or lob == "IBMS"
        is_dental = plan_type.lower() == "dental" or lob == "IDTL"

        if not is_supplement and not is_dental:
            # For MA: skip if term date is genuinely in the past
            if term_date is not None and term_date < today:
                continue

        records.append({
            "carrier": "BCBS",
            "member_id": member_id,
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "Plan"),
            "plan_type": plan_type,
            "effective_date": _parse_date(row, "Effective Date"),
            # Supplement: store renewal date but mark it so dashboard ignores it for terminations
            "term_date": None if is_supplement else term_date,
            "renewal_date": term_date if is_supplement else None,
            "dob": _parse_date(row, "Date Of Birth"),
            "phone": _str(row, "Home Phone"),
            "county": _str(row, "County"),
            "agent_id": _str(row, "Producer ID"),
            "status": "active",
        })

    if not records:
        raise ValueError("BCBS file parsed successfully but contained 0 active records.")

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
