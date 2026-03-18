"""
Humana BOB parser.
Status filter: "Active Policy" (confirmed from live file March 2026).
Primary key: Humana ID (MBI is masked as XXXXX...).
Confirmed columns from live file March 2026.
"""
import pandas as pd

REQUIRED_COLUMNS = {"MbrFirstName", "MbrLastName", "Humana ID"}


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_csv(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Humana file: {e}")

    df.columns = df.columns.str.strip()
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Humana file missing required columns: {missing}")

    if "Status" in df.columns:
        df = df[df["Status"].str.strip() == "Active Policy"]

    df = df[df["Humana ID"].notna() & (df["Humana ID"].str.strip() != "")]
    df = df.copy()

    records = []
    for _, row in df.iterrows():
        humana_id = _str(row, "Humana ID")
        first = _str(row, "MbrFirstName")
        last = _str(row, "MbrLastName")
        raw_mbi = _str(row, "Medicare No")
        records.append({
            "carrier": "Humana",
            "member_id": humana_id,
            "mbi": "" if raw_mbi.startswith("XXXXX") else raw_mbi.upper(),
            "first_name": first,
            "last_name": last,
            "full_name": f"{first} {last}".strip(),
            "plan_name": _str(row, "Plan Name"),
            "plan_type": _str(row, "Plan Type"),
            "effective_date": _parse_date(row, "Effective Date"),
            "term_date": _parse_date(row, "Inactive Date"),
            "dob": _parse_date(row, "Birth Date"),
            "phone": _str(row, "Primary Phone"),
            "county": _str(row, "Mail Cnty"),
            "agent_id": _str(row, "NPN"),
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
