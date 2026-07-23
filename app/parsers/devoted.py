"""
Devoted Health BOB parser.

Two formats:
  1. Older CSV (raw API dump, snake_case) — unique member_id (UUID, not MBI).
  2. July-2026+ XLSX "Application Status Report" — single "Full Name", "Birth Date",
     "Current Status", NO member_id. Keyed by name+DOB (synthesized member_id),
     mirroring the UHC agent-centric BOB. Filter to Current Status == Enrolled.
"""
import hashlib
import os
import pandas as pd


REQUIRED_COLUMNS = {"member_id", "first_name", "last_name"}
# The Application-Status XLSX prefixes every header with this.
_APP_PREFIX = "application status report"


def _synth_member_id(first, last, dob) -> str:
    """Stable synthetic member_id for the no-ID Application-Status BOB (name+DOB).
    Deterministic → idempotent re-import; distinct name+DOB → distinct id."""
    seed = f"{(first or '').strip().lower()}|{(last or '').strip().lower()}|{(dob or '')}"
    return "DVND-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16].upper()


def _split_full_name(full):
    """'Brandi Tucker' → ('Brandi', 'Tucker'); 'Mary Jane Smith' → ('Mary','Jane Smith')."""
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def parse(filepath: str) -> list[dict]:
    """Parse a Devoted BOB (CSV member_id format OR XLSX Application-Status format)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xls"):
        try:
            sheets = pd.read_excel(filepath, dtype=str, sheet_name=None)  # dict: name -> df
        except Exception as e:
            raise ValueError(f"Could not read Devoted file: {e}")
        # Pick the sheet whose headers carry the Application-Status prefix (the real
        # BOB has a pivot-table 'Sheet1' in front of the data sheet); else first sheet.
        xdf = None
        for _name, _df in sheets.items():
            cols = [str(c).strip().lower() for c in _df.columns]
            if any(c.startswith(_APP_PREFIX) for c in cols):
                xdf = _df
                break
        if xdf is None:
            xdf = next(iter(sheets.values()))
        xdf.columns = xdf.columns.str.strip()
        if any(str(c).strip().lower().startswith(_APP_PREFIX) for c in xdf.columns):
            # Two Application-Status variants: the RICH full BOB has an Mbi column
            # (real CMS MBIs + plan ID/type/address); the older lossy one does not.
            has_mbi_col = any(
                str(c).strip().lower() == "application status report mbi"
                for c in xdf.columns
            )
            if has_mbi_col:
                return _parse_application_status_rich(xdf)
            return _parse_application_status(xdf)
        # An XLSX that isn't the Application-Status shape: fall through to the
        # snake_case path below (some exports are just CSV-content saved as XLSX).
        df = xdf
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    else:
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


def _parse_application_status(df):
    """July XLSX Application-Status Report: single Full Name, Birth Date, Current
    Status, no member_id. Strip the 'Application Status Report ' prefix, keep only
    Enrolled, split the name, synthesize member_id from name+DOB."""
    def col(short):
        return f"Application Status Report {short}"

    records = []
    for _, row in df.iterrows():
        status_raw = _str(row, col("Current Status")).upper()
        if status_raw != "ENROLLED":
            continue                                # active book only
        full = _str(row, col("Full Name"))
        first, last = _split_full_name(full)
        if not last and not first:
            continue
        first, last = first.title(), last.title()   # source is ALL-CAPS
        dob = _parse_date(row, col("Birth Date"))
        records.append({
            "carrier": "Devoted",
            "member_id": _synth_member_id(first, last, dob),
            "mbi": "",
            "first_name": first,
            "last_name": last,
            "full_name": full or f"{first} {last}".strip(),
            "plan_name": _str(row, col("Plan Name")),
            "plan_type": "",
            "effective_date": _parse_date(row, col("Start Date")),
            "term_date": None,                      # Enrolled-only book
            "dob": dob,
            "phone": "",
            "county": "",
            "agent_id": _str(row, col("Agent Npn")),
            "status": "active",
        })
    return records


def _yesno(row, col_short) -> bool:
    """True iff the 'Yes / No' column reads 'Yes' (case-insensitive)."""
    return _str(row, f"Application Status Report {col_short}").strip().lower() == "yes"


def _parse_application_status_rich(df):
    """The FULL Devoted BOB ('Application Status Report' with an Mbi column):
    real CMS MBI + plan ID/type + address + writing-agent name + application date
    + competing-app flags. Keyed by the real MBI (no synthetic id). Enrolled OR
    Approved => active; any other status skipped. Captures is_winning_app +
    application_date for the same-MBI dedup tie-break (app/upload.py)."""
    def col(short):
        return f"Application Status Report {short}"

    records = []
    for _, row in df.iterrows():
        status_raw = _str(row, col("Current Status")).strip().lower()
        if status_raw not in ("enrolled", "approved"):
            continue                                # active book only

        mbi = _str(row, col("Mbi")).upper()
        if not mbi:
            continue                                # rich path is MBI-keyed

        first = _str(row, col("First Name")).title()
        last = _str(row, col("Last Name")).title()
        full = _str(row, col("Full Name"))
        if not first and not last:
            first, last = _split_full_name(full)
            first, last = first.title(), last.title()

        records.append({
            "carrier": "Devoted",
            "member_id": mbi,                       # MBI is the key
            "mbi": mbi,
            "first_name": first,
            "last_name": last,
            "full_name": full or f"{first} {last}".strip(),
            "dob": _parse_date(row, col("Birth Date")),
            "phone": _str(row, col("Phone Number")),
            "address1": _str(row, col("Address")),
            "city": _str(row, col("City")),
            "state": _str(row, col("State")),
            "zip_code": _str(row, col("Zip Code")),
            "county": _str(row, col("County")),
            "effective_date": _parse_date(row, col("Start Date")),
            "term_date": (_parse_date(row, col("Plan End Date"))
                          or _parse_date(row, col("Disenrollment Date"))),
            "plan_name": _str(row, col("Plan Name")),
            "contract_code": _str(row, col("Plan ID")).upper(),   # CMS H-code, e.g. H5299-013
            "plan_type": _str(row, col("Plan Type")),
            "agent_name": _str(row, col("Agent Name")),
            "agent_id": _str(row, col("Agent Npn")),
            "application_date": _parse_date(row, col("Application Date")),
            "is_winning_app": _yesno(row, "Is Winning App (Yes / No)"),
            "commission_type": ("initial"
                                if _yesno(row, "Is New to Medicare Advantage (Yes / No)")
                                else "renewal"),
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
