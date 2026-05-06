"""
Healthspring (Cigna) BOB / commission payment parser.

AJ downloads a file with columns:
  0 Payment Type, 1 Payment Description, 2 Writing Broker NPN,
  3 Writing Broker Name, 4 Earner NPN, 5 Earner Name,
  6 Pay Period, 7 Payment Amount, 8 Member ID, 9 MBI

No name, DOB, or address — MBI and Member ID are the identifiers.
We produce one record per unique MBI (skipping summary/negative rows).
"""
import re
import openpyxl
from datetime import date, datetime

SKIP_ACTIONS = {"payment type"}  # header row guard


def parse(filepath: str) -> list[dict]:
    try:
        wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
    except Exception as e:
        raise ValueError(f"Could not read Healthspring file: {e}")

    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    seen = {}  # mbi → record

    for row in rows:
        if not any(row):
            continue
        if len(row) < 10:
            continue

        payment_type = str(row[0] or "").strip()
        # Skip summary rows (they have no MBI) and header guard
        if not payment_type or payment_type.lower() in SKIP_ACTIONS:
            continue
        # Skip summary formula rows (col 6 contains "N x.55")
        if re.search(r'[\d,]+\s*x\.?\s*\.?\d+', str(row[6] or "")):
            continue

        amount = row[7]
        if not isinstance(amount, (int, float)):
            continue

        mbi       = str(row[9] or "").strip()
        member_id = str(row[8] or "").strip()

        if not mbi and not member_id:
            continue

        # Determine active vs termed from payment type
        payment_lower = payment_type.lower()
        if "disenroll" in payment_lower or "rapid" in payment_lower:
            status = "termed"
        else:
            status = "active"

        effective_date = _parse_date(row[6])

        key = mbi or member_id
        rec = {
            "carrier":        "Healthspring",
            "member_id":      member_id or mbi,
            "mbi":            mbi or None,
            "first_name":     "",
            "last_name":      "",
            "full_name":      "",
            "plan_name":      "",
            "plan_type":      "MAPD",
            "effective_date": effective_date,
            "term_date":      None,
            "renewal_date":   None,
            "dob":            None,
            "phone":          "",
            "county":         "",
            "address1":       "",
            "city":           "",
            "state":          "",
            "zip_code":       "",
            "agent_id":       str(row[2] or "").strip(),
            "status":         status,
        }

        if key not in seen:
            seen[key] = rec

    return list(seen.values())


def _parse_date(val):
    if val is None:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None
