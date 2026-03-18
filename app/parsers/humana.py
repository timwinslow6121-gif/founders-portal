"""
Humana BOB parser.

Format: CSV
Unique ID: Humana ID (MBI is masked as XXXXX12HN86 — not usable)
Active filter: export is active-only — no filter needed
Name fields: MbrFirstName / MbrLastName
"""

import pandas as pd


REQUIRED_COLUMNS = {"MbrFirstName", "MbrLastName"}


def parse(filepath: str) -> list[dict]:
    """
    Parse a Humana CSV export and return a list of normalized policy dicts.
    Uses HumanaID as the primary key since MBI is masked.
    """
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Humana file: {e}")

    df.columns = df.columns.str.strip()

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Humana file missing required columns: {missing}")

    # Determine the ID column — Humana exports vary slightly
    id_col = None
    for candidate in ("HumanaId", "HumanaID", "MemberId", "MemberID", "Member ID"):
        if candidate in df.columns:
            id_col = candidate
            break

    if id_col is None:
        raise ValueError("Humana file: cannot find member ID column (tried HumanaId, MemberId, Member ID)")

    df = df[df[id_col].notna() & (df[id_col].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        humana_id = _str(row, id_col)
        first = _str(row, "MbrFirstName")
        last = _str(row, "MbrLastName")

        # MBI is present but masked — store it as-is for reference
        raw_mbi = _str(row, "Medicare_ID") or _str(row, "MedicareID") or _str(row, "MBI") or ""

        records.append({
            "carrier": "Humana",
            "member_id": humana_id,    # Humana ID is primary key
            "mbi": raw_mbi if not raw_mbi.startswith("XXXXX") else "",
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "PlanName") or _str(row, "Plan Name") or _str(row, "PBP Name"),
            "plan_type": _str(row, "PlanType") or _str(row, "Plan Type"),
            "effective_date": _parse_date(row, "EffectiveDate") or _parse_date(row, "Effective Date"),
            "term_date": _parse_date(row, "TermDate") or _parse_date(row, "Term Date"),
            "dob": _parse_date(row, "MbrDOB") or _parse_date(row, "DOB"),
            "phone": _str(row, "Phone") or _str(row, "PhoneNumber"),
            "county": _str(row, "County"),
            "agent_id": _str(row, "AgentID") or _str(row, "Agent ID"),
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
