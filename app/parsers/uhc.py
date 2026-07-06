"""
UHC (UnitedHealthcare) BOB parser.

File format: XLSX downloaded from UHC producer portal.
Row 0: blank, Row 1: confidentiality notice, Row 2: column headers, Row 3+: data.
pandas header=2 reads this correctly.

Key columns: mbiNumber, memberFirstName, memberLastName, memberAddress1,
memberCity, memberZip, memberState, dateOfBirth, memberPhone, product,
planName, memberCounty, policyEffectiveDate, policyTermDate, termReasonCode, agentId
"""
import hashlib
import pandas as pd

REQUIRED_COLUMNS = {"mbiNumber", "memberFirstName", "memberLastName"}
# The July-2026+ agent-centric BOB has NO mbiNumber — only name + DOB + planStatus.
NO_MBI_REQUIRED = {"memberFirstName", "memberLastName", "planStatus"}
UHC_NO_TERM_SENTINEL = "2300-01-01"


def _synth_member_id(first, last, dob) -> str:
    """Stable synthetic member_id for the no-MBI UHC BOB (name + DOB). The DB
    requires a non-null Policy.member_id; UHC's July BOB carries no member
    identifier, so key on name+DOB. Deterministic → re-import is idempotent;
    distinct name+DOB → distinct id (no collision)."""
    seed = f"{(first or '').strip().lower()}|{(last or '').strip().lower()}|{(dob or '')}"
    return "UHCND-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16].upper()


def parse(filepath: str) -> list[dict]:
    try:
        df = pd.read_excel(filepath, header=2, dtype=str)
    except Exception as e:
        raise ValueError(f"Could not read UHC file: {e}")

    df.columns = df.columns.str.strip()
    cols = set(df.columns)
    if REQUIRED_COLUMNS <= cols:
        return _parse_mbi_format(df)
    if NO_MBI_REQUIRED <= cols:
        return _parse_no_mbi_format(df)
    missing = REQUIRED_COLUMNS - cols
    raise ValueError(f"UHC file missing required columns: {missing}")


def _parse_mbi_format(df):
    df = df[df["mbiNumber"].notna() & (df["mbiNumber"].str.strip() != "")].copy()

    records = []
    for _, row in df.iterrows():
        mbi      = _str(row, "mbiNumber").upper()
        first    = _str(row, "memberFirstName").title()
        last     = _str(row, "memberLastName").title()
        raw_term = _str(row, "policyTermDate")
        term_date = None
        if raw_term and raw_term != UHC_NO_TERM_SENTINEL:
            term_date = _parse_date(row, "policyTermDate")

        records.append({
            "carrier":        "UHC",
            "member_id":      mbi,
            "mbi":            mbi,
            "first_name":     first,
            "last_name":      last,
            "full_name":      f"{first} {last}".strip(),
            "plan_name":      _str(row, "planName"),
            "plan_type":      _str(row, "product"),
            "effective_date": _parse_date(row, "policyEffectiveDate"),
            "term_date":      term_date,
            "renewal_date":   None,
            "dob":            _parse_date(row, "dateOfBirth"),
            "phone":          _str(row, "memberPhone"),
            "county":         _str(row, "memberCounty"),
            "address1":       _str(row, "memberAddress1").title(),
            "city":           _str(row, "memberCity").title(),
            "state":          _str(row, "memberState").upper(),
            "zip_code":       _str(row, "memberZip"),
            "agent_id":       _str(row, "agentId"),
            "status":         "active" if not term_date else "termed",
        })
    return records


def _parse_no_mbi_format(df):
    """July agent-centric BOB: no MBI. Status from planStatus (A=active, else termed);
    member_id synthesized from name+DOB. mbi left empty (none available)."""
    df = df[df["memberLastName"].notna() & (df["memberLastName"].str.strip() != "")].copy()

    records = []
    for _, row in df.iterrows():
        first  = _str(row, "memberFirstName").title()
        last   = _str(row, "memberLastName").title()
        dob    = _parse_date(row, "dateOfBirth")
        status = "active" if _str(row, "planStatus").upper().startswith("A") else "termed"
        raw_term = _str(row, "policyTermDate")
        term_date = None
        if status == "termed" and raw_term and raw_term != UHC_NO_TERM_SENTINEL:
            term_date = _parse_date(row, "policyTermDate")

        records.append({
            "carrier":        "UHC",
            "member_id":      _synth_member_id(first, last, dob),
            "mbi":            "",                      # no MBI in this BOB
            "first_name":     first,
            "last_name":      last,
            "full_name":      f"{first} {last}".strip(),
            "plan_name":      _str(row, "planName"),
            "plan_type":      _str(row, "product"),
            "effective_date": None,                   # not in this BOB
            "term_date":      term_date,
            "renewal_date":   None,
            "dob":            dob,
            "phone":          _str(row, "memberPhone"),
            "county":         "",
            "address1":       _str(row, "memberAddress1").title(),
            "city":           _str(row, "memberCity").title(),
            "state":          _str(row, "memberState").upper(),
            "zip_code":       _str(row, "memberZip"),
            "agent_id":       _str(row, "agentId"),
            "status":         status,
        })
    return records


def _str(row, col: str) -> str:
    val = row.get(col, "")
    if pd.isna(val):
        return ""
    return str(val).strip()


def _parse_date(row, col: str):
    val = row.get(col, "")
    if pd.isna(val) or str(val).strip() in ("", UHC_NO_TERM_SENTINEL):
        return None
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None
