"""
Aetna BOB parser (rewritten 2026-06-23 to the REAL format).

Both upload paths share core columns by NAME (so AJ's agency-wide file and the
per-agent download both parse): Medicare Number, Member ID, Member Name, Member State,
Plan ID, Coverage Period, Effective Date, Writing Agent Name, CMS New. There is NO
Term Date column. Reads .xlsx (header row 0). Extra commission/tax columns are ignored.
Names → "First MI. Last" via app.names.normalize_person_name.
"""
import os
import pandas as pd
from app.names import normalize_person_name

XLSX_REQUIRED = {"Medicare Number", "Member Name", "Writing Agent Name"}
CSV_REQUIRED = {"Medicare Number", "First Name", "Writing Agent NPN"}
_TERM_SENTINEL = "3000-01-01"


def parse(filepath: str) -> list[dict]:
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".csv":
        try:
            df = pd.read_csv(filepath, dtype=str)
        except Exception as e:
            raise ValueError(f"Could not read Aetna file: {e}")
        df.columns = df.columns.str.strip()
        missing = CSV_REQUIRED - set(df.columns)
        if missing:
            raise ValueError(f"Aetna CSV missing required columns: {missing}")
        return _parse_csv_format(df)

    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read Aetna file: {e}")
    df.columns = df.columns.str.strip()

    # Two XLSX shapes exist. The older agency file has "Member Name" + "Writing
    # Agent Name". The July-2026+ download is an XLSX with the SAME split columns
    # as the CSV/per-agent format ("First Name"/"Last Name"/"Writing Agent NPN" +
    # "First/Last Name"). Route each to its matching parser instead of rejecting
    # the newer format (which errored AJ's July upload).
    cols = set(df.columns)
    if XLSX_REQUIRED <= cols:
        return _parse_xlsx_format(df)
    if CSV_REQUIRED <= cols:
        return _parse_csv_format(df)
    missing = XLSX_REQUIRED - cols
    raise ValueError(f"Aetna file missing required columns: {missing}")


def _parse_xlsx_format(df):
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
            "cms_contract_number": _str(row, "CMS Contract Number"),
            "pbp_code": _str(row, "PBP Code"),
        })
    return records


def _parse_csv_format(df):
    df = df[df["Medicare Number"].notna() &
            (df["Medicare Number"].astype(str).str.strip() != "")].copy()
    records = []
    for _, row in df.iterrows():
        mbi = _str(row, "Medicare Number").upper()
        if not mbi:
            continue
        status_raw = _str(row, "Member Status").upper()
        status = "active" if status_raw == "A" else "termed"
        first = _tc(_str(row, "First Name"))
        last = _tc(_str(row, "Last Name"))
        mi = _str(row, "Middle Initial").strip(".").upper()[:1]
        full = " ".join(x for x in [first, (mi + "." if mi else ""), last] if x)
        addr1 = _str(row, "Address Line 1")
        addr2 = _str(row, "Address Line 2")
        if addr2:
            addr1 = f"{addr1}, {addr2}".strip(", ")
        term = _parse_date(row, "Term Date")
        records.append({
            "carrier": "Aetna",
            "member_id": mbi,
            "mbi": mbi,
            "carrier_member_id": _str(row, "Member ID"),
            "first_name": first, "last_name": last, "full_name": full,
            "agent_id": _str(row, "Writing Agent NPN"),     # NPN → resolve_writing_agent
            "agent_name": " ".join(p for p in [_str(row, "Writing Agent First Name"),
                                               _str(row, "Writing Agent Last Name")] if p),
            "effective_date": _parse_date(row, "Coverage Effective Date"),
            "term_date": term,
            "renewal_date": None,
            "state": _str(row, "State"),
            "address1": addr1, "city": _str(row, "City"), "zip_code": _str(row, "Zip Code"),
            "plan_name": _str(row, "Plan Name"),
            "plan_type": "", "phone": _str(row, "Phone Number"),
            "county": "", "dob": _parse_date(row, "Date of Birth"),
            "commission_type": None,
            "status": status,
            "cms_contract_number": _str(row, "CMS Contract Number"),
            "pbp_code": _str(row, "PBP Code"),
        })
    return records


def _tc(w):
    return w[:1].upper() + w[1:].lower() if w else w


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def _parse_date(row, col: str):
    val = row.get(col, "")
    if not val or (isinstance(val, float) and pd.isna(val)) or str(val).strip() == "":
        return None
    if str(val).strip().startswith(_TERM_SENTINEL):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
