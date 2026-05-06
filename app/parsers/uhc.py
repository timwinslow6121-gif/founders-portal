"""
UHC (UnitedHealthcare) BOB / commission statement parser.

AJ downloads a file called "Book of business" from UHC which is actually
a commission statement with columns:
  0 Statement Date, 1 Writing Agent Name, 2 Member Name,
  3 Original Effective Date, 4 Commission Action, 5 Commission,
  6 Term Reason, 7 Term Date

No MBI or address data — member name + effective date are the only identifiers.
We produce one record per unique active member (Renewal or New action).
member_id = normalized "LAST FIRST" for Policy deduplication.
"""
import re
import openpyxl
from datetime import date

UHC_NO_TERM_SENTINEL = "2300-01-01"
ACTIVE_ACTIONS = {"Renewal", "New"}


def parse(filepath: str) -> list[dict]:
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"Could not read UHC file: {e}")

    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    seen_members = {}  # member_id → record (keep most recent effective_date row)

    for row in rows:
        if not any(row):
            continue
        action = str(row[4] or "").strip()
        if action not in ACTIVE_ACTIONS:
            continue

        raw_name = str(row[2] or "").strip()
        if not raw_name:
            continue

        # Parse "LAST, FIRST M." → first, last
        first, last = _split_name(raw_name)
        member_id = f"UHC-{last.upper()}-{first.upper()}"

        term_raw = str(row[7] or "").strip()
        term_date = None
        if term_raw and term_raw != UHC_NO_TERM_SENTINEL:
            term_date = _parse_date(row[7])

        eff_date = _parse_date(row[3])

        rec = {
            "carrier":        "UHC",
            "member_id":      member_id,
            "mbi":            None,
            "first_name":     first.title(),
            "last_name":      last.title(),
            "full_name":      f"{first.title()} {last.title()}".strip(),
            "plan_name":      "",
            "plan_type":      "MAPD",
            "effective_date": eff_date,
            "term_date":      term_date,
            "renewal_date":   None,
            "dob":            None,
            "phone":          "",
            "county":         "",
            "address1":       "",
            "city":           "",
            "state":          "",
            "zip_code":       "",
            "agent_id":       "",
            "status":         "active" if not term_date else "termed",
        }

        # If we've seen this member already, keep the one with the latest effective_date
        if member_id not in seen_members:
            seen_members[member_id] = rec
        else:
            existing = seen_members[member_id]
            if eff_date and (not existing["effective_date"] or eff_date > existing["effective_date"]):
                seen_members[member_id] = rec

    return list(seen_members.values())


def _split_name(raw: str):
    """'ADAMS, BARBARA R.' → ('BARBARA', 'ADAMS')"""
    if "," in raw:
        parts = raw.split(",", 1)
        last = parts[0].strip()
        first_part = parts[1].strip().split()
        first = first_part[0] if first_part else ""
    else:
        words = raw.strip().split()
        if len(words) >= 2:
            last = words[-1]
            first = words[0]
        else:
            last = raw.strip()
            first = ""
    return first, last


def _parse_date(val):
    if val is None:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s == UHC_NO_TERM_SENTINEL:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None
