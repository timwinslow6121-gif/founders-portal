import csv
import io
import json
import re
from datetime import date, datetime

import openpyxl
from dateutil.relativedelta import relativedelta
from flask import (abort, flash, redirect, render_template,
                   request, url_for, current_app)
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db
from app.models import CommissionStatement, User, AgentCarrierContract, Policy, PolicyPayment
from app.commission import commission_bp
from app.commission.payments import build_payments

SPLIT_RATE = 0.55


def _scan_summary(ws):
    """
    Scan every cell in the sheet for AJ's manually typed summary rows.
    AJ places these inconsistently — column and row position varies month to month.

    Looks for:
      - Gross×rate row:  "7,566.59 x.55"  or  "$202.44 x.525"  etc.
      - Paid row:        a numeric cell adjacent to or near a gross×rate cell,
                         OR a cell matching "$N + $N" pattern (UHC style)

    Returns:
      (paid, stated_rate)
      paid        — the numeric amount AJ says was paid (float or None)
      stated_rate — the split rate AJ used in his formula (float or None)
                    Callers should compare this against the contract rate.
    """
    all_cells = []
    for row in ws.iter_rows():
        for cell in row:
            all_cells.append(cell)

    paid = None
    stated_rate = None

    for cell in all_cells:
        val = str(cell.value or "").strip()

        # Pattern: "NNN x .55" or "$NNN,NNN.NN x.525" — gross × split summary
        m = re.search(r'[\$]?([\d,]+\.?\d*)\s*x\.?\s*(\.?\d+)', val)
        if m:
            try:
                rate = float(m.group(2))
                if 0 < rate < 1:
                    stated_rate = rate
                elif rate > 1:          # e.g. "x55" instead of "x.55"
                    stated_rate = rate / 100
            except ValueError:
                pass
            # The paid value is often the numeric cell immediately to the right
            # or below this cell
            right = ws.cell(row=cell.row, column=cell.column + 1)
            below = ws.cell(row=cell.row + 1, column=cell.column)
            for candidate in (right, below):
                if isinstance(candidate.value, (int, float)):
                    paid = float(candidate.value)
                    break
            continue

        # Pattern: "$4,161.62 + $130.81" — paid = numeric in next cell
        if re.search(r'^\$[\d,]+\.\d+\s*\+\s*[\$\d]', val):
            right = ws.cell(row=cell.row, column=cell.column + 1)
            below = ws.cell(row=cell.row + 1, column=cell.column)
            for candidate in (right, below):
                if isinstance(candidate.value, (int, float)):
                    if paid is None:   # don't overwrite if already found
                        paid = float(candidate.value)
                    break
            continue

        # Pattern: "$283.17 + 27(last month)" — free-text paid note, extract numeric
        m2 = re.search(r'^\$?([\d,]+\.\d{2})\s*\+\s*[\d\$]', val)
        if m2:
            try:
                if paid is None:
                    paid = float(m2.group(1).replace(',', ''))
            except ValueError:
                pass

    return paid, stated_rate


def _parse_uhc(ws):
    # April 2026 UHC column layout (0-indexed):
    #  col3:  Statement Date     col5:  Writing Agent Name
    #  col7:  Member Name        col8:  MedicareID (MBI)
    #  col11: Original Eff Date  col19: Commission Action
    #  col23: Commission         col24: Term Reason    col28: Term Date
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    bonus = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        action     = str(row[19] or "").strip()
        commission = row[23]

        if stmt_date is None and row[3] and isinstance(row[3], datetime):
            stmt_date = row[3].date()

        if action in ("New Chargeback",):
            amt = float(commission) if commission and isinstance(commission, (int, float)) else None
            if amt:
                gross += amt
            line_items.append({
                "mbi":         str(row[8] or "").strip(),
                "member":      str(row[7] or ""),
                "eff_date":    str(row[11].date() if isinstance(row[11], datetime) else row[11] or ""),
                "action":      action,
                "amount":      amt,
                "term_reason": str(row[24] or ""),
            })
            continue

        if action in ("Renewal", "New"):
            amt = float(commission) if commission and isinstance(commission, (int, float)) else None
            if amt:
                gross += amt
            line_items.append({
                "mbi":         str(row[8] or "").strip(),
                "member":      str(row[7] or ""),
                "eff_date":    str(row[11].date() if isinstance(row[11], datetime) else row[11] or ""),
                "action":      action,
                "amount":      amt,
                "term_reason": str(row[24] or ""),
            })

    return gross, bonus, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_aetna(ws):
    # April 2026 Aetna CSV column layout (0-indexed):
    #  col0:  Payment Date       col1:  Medicare Number (MBI)
    #  col4:  Member Name        col6:  Sales Event (action)
    #  col9:  Plan ID            col12: Coverage Period
    #  col14: Writing Agent NPN  col16: Writing Agent Name
    #  col20: Payee Amount
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip footer rows (e.g. "Total Payee Amount: $1461.97" in col0)
        col0 = str(row[0] or "").strip()
        if col0.lower().startswith("total"):
            continue
        # Skip summary rows
        if re.search(r'[\d,]+\.?\d*\s*x', str(row[9] or "")):
            continue

        amount = row[20] if len(row) > 20 else None   # Payee Amount
        mbi    = str(row[1] or "").strip()             # Medicare Number

        # Parse stmt_date from Payment Date (col0) — may be string "YYYY-MM-DD"
        if stmt_date is None and row[0]:
            if isinstance(row[0], datetime):
                stmt_date = row[0].date()
            elif isinstance(row[0], date):
                stmt_date = row[0]
            else:
                try:
                    stmt_date = datetime.strptime(str(row[0]).strip(), "%Y-%m-%d").date()
                except ValueError:
                    pass

        # Convert string amounts (CSV comes in as strings)
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", "").replace("$", "").strip())
            except ValueError:
                amount = None

        if amount and isinstance(amount, (int, float)) and float(amount) != 0:
            gross += float(amount)
            line_items.append({
                "mbi":      mbi,
                "member":   str(row[4] or ""),
                "plan":     str(row[9] or ""),
                "eff_date": str(row[12] or ""),
                "action":   str(row[6] or ""),
                "amount":   float(amount),
            })

    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_humana(ws):
    paid_scan, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross     = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\$\d,]+\.?\d*\s*x', str(row[8] or "")):
            continue
        if re.search(r'[\$\d,]+\.?\d*\s*x', str(row[7] or "")):
            continue

        amount  = row[8]   # PaidAmount
        comment = str(row[9] or "").strip()

        if stmt_date is None and row[1] and isinstance(row[1], datetime):
            stmt_date = row[1].date()

        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            line_items.append({
                "member":  str(row[4] or ""),
                "month":   str(row[6] or ""),
                "action":  comment,
                "amount":  float(amount),
                "product": str(row[7] or ""),
            })

    # Humana pays Tim directly — use scanned paid if available, otherwise gross
    paid = paid_scan if paid_scan is not None else gross
    return gross, 0.0, paid, stmt_date, line_items, stated_rate


def _parse_bcbs(ws):
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None  # will be set from file content or filename fallback

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\$\d,]+\.?\d*\s*x', str(row[9] or "")):
            continue
        col13 = str(row[13] or "").strip() if len(row) > 13 else ""
        if col13.startswith("="):
            continue
        col12 = str(row[12] or "").strip() if len(row) > 12 else ""
        if col12.lower() == "total:":
            continue

        commission = row[13] if len(row) > 13 else None
        if commission and isinstance(commission, (int, float)) and float(commission) != 0:
            gross += float(commission)
            line_items.append({
                "member":     str(row[3] or ""),
                "plan":       str(row[6] or ""),
                "group_type": str(row[2] or ""),
                "eff_date":   str(row[5] or ""),
                "action":     str(row[2] or ""),
                "amount":     float(commission),
            })

    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_devoted(ws):
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\$\d,]+\s*x\.?\s*\.?\d+', str(row[8] or "")):
            continue

        amount = row[11]  # Base Amount
        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            line_items.append({
                "member":    f"{row[5] or ''} {row[6] or ''}".strip(),
                "member_id": str(row[3] or ""),
                "eff_date":  str(row[7] or ""),
                "period":    str(row[10] or ""),
                "action":    str(row[9] or "New/Renewal"),
                "amount":    float(amount),
            })

        if stmt_date is None and row[0]:
            try:
                stmt_date = datetime.strptime(str(row[0]), "%m/%d/%Y").date()
            except Exception:
                pass

    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_healthspring(ws):
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\d,]+\s*x\.?\s*\.?\d+', str(row[6] if len(row) > 6 else "")):
            continue

        amount = row[7] if len(row) > 7 else None
        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            pay_period = row[6]
            if stmt_date is None and isinstance(pay_period, datetime):
                stmt_date = pay_period.date()
            line_items.append({
                "member":      str(row[8] or ""),
                "mbi":         str(row[9] or ""),
                "action":      str(row[0] or ""),
                "description": str(row[1] or ""),
                "amount":      float(amount),
            })

    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_wellable(ws):
    """Wellable advance commissions — flagged as clawback-eligible advances."""
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\$\d,]+\.?\d*\s*x\s*\.?\d+', str(row[16] if len(row) > 16 else "")):
            continue

        advance_amount = row[16] if len(row) > 16 else None
        if advance_amount and isinstance(advance_amount, (int, float)):
            gross += float(advance_amount)
            app_date = row[17] if len(row) > 17 else None
            if stmt_date is None and isinstance(app_date, datetime):
                stmt_date = app_date.date()
            line_items.append({
                "member":         str(row[5] or ""),
                "policy":         str(row[4] or ""),
                "plan":           str(row[7] or ""),
                "premium":        float(row[12]) if row[12] else 0.0,
                "advance_pct":    float(row[13]) if row[13] else 0.0,
                "advance_months": str(row[14] or ""),
                "action":         str(row[15] or ""),
                "amount":         float(advance_amount),
                "is_advance":     True,
            })

    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


def _csv_bytes_to_workbook(file_bytes):
    """Convert a CSV file (bytes) into an openpyxl Workbook so the rest of
    the commission pipeline can treat it identically to an XLSX file.
    Values are stored as strings; _parse_aetna handles string-to-float conversion."""
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in reader:
        ws.append(row)
    return wb


_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date_from_filename(filename):
    """
    Extract a statement month/year from a filename as a last-resort fallback.
    Handles patterns like:
      UHC_March_2026.xlsx
      BCBS April 2026 Commission.xlsx
      Humana-2026-03.xlsx
      statement_2026_04.csv
    Returns date(year, month, 1) or None if no match.
    """
    if not filename:
        return None
    name = filename.lower()

    # Pattern 1: named month + 4-digit year  e.g. "march_2026", "april 2026"
    m = re.search(
        r'(' + '|'.join(_MONTH_NAMES.keys()) + r')[_\-\s]+(\d{4})',
        name
    )
    if m:
        month = _MONTH_NAMES[m.group(1)]
        year = int(m.group(2))
        if 2020 <= year <= 2099:
            return date(year, month, 1)

    # Pattern 2: 4-digit year + named month  e.g. "2026_march"
    m = re.search(
        r'(\d{4})[_\-\s]+(' + '|'.join(_MONTH_NAMES.keys()) + r')',
        name
    )
    if m:
        year = int(m.group(1))
        month = _MONTH_NAMES[m.group(2)]
        if 2020 <= year <= 2099:
            return date(year, month, 1)

    # Pattern 3: YYYY-MM or YYYY_MM  e.g. "2026-03", "2026_04"
    m = re.search(r'(\d{4})[_\-](\d{2})', name)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 2020 <= year <= 2099 and 1 <= month <= 12:
            return date(year, month, 1)

    return None


def _detect_carrier(ws):
    headers = [str(c.value or "").lower() for c in ws[1]]
    header_str = " ".join(headers)
    if "commission action" in header_str and "writing agent" in header_str:
        return "UHC"
    if "payee amount" in header_str and "sales event" in header_str:
        return "Aetna"
    if "commrundt" in header_str or "grpname" in header_str:
        return "Humana"
    if "billed amount" in header_str or ("group type" in header_str and "customer name" in header_str):
        return "BCBS"
    if "member hicn" in header_str or "agent npn" in header_str:
        return "Devoted"
    if "payment type" in header_str and "medicare beneficiary identifier" in header_str:
        return "Healthspring"
    if "distributor number" in header_str and "advance type" in header_str:
        return "Wellable"
    return None


def _normalize_name(s):
    """Normalize agent name for fuzzy matching.
    Handles formats:
      - 'WINSLOW, TIMOTHY JAMES' → 'timothy winslow'
      - 'WINSLOW TIMOTHY J'      → 'timothy winslow'
      - 'Timothy Winslow'        → 'timothy winslow'
    """
    s = str(s or "").strip().lower()

    if "," in s:
        # "WINSLOW, TIMOTHY JAMES" → ["winslow", "timothy james"]
        parts = [p.strip() for p in s.split(",", 1)]
        last  = parts[0].strip()
        first = parts[1].strip().split()[0] if parts[1].strip() else ""
        return f"{first} {last}".strip()

    words = s.split()
    if len(words) == 1:
        return s
    if len(words) == 2:
        # "timothy winslow" — already normalized
        return s
    # 3+ words: could be "WINSLOW TIMOTHY J" (last first initial)
    # or "Timothy James Winslow" (first middle last)
    # Check if first word looks like a last name by seeing if it matches
    # any known last name pattern — simplest: try both orderings
    # Return "first last" by taking word[1] word[0] (last-first-initial format)
    # This handles Humana's "WINSLOW TIMOTHY J" → "timothy winslow"
    return f"{words[1]} {words[0]}".strip()


def _detect_agent_id(ws, carrier):
    """Extract agent name from file and match to a User in the database."""
    agent_col_map = {
        "UHC":          5,   # Writing Agent Name (col F, index 5)
        "Aetna":       16,   # Writing Agent Name (col Q, index 16)
        "Humana":       2,   # WaName (col C, index 2)
        "BCBS":         1,   # Agent Name (col B, index 1)
        "Devoted":      2,   # Agent Name (col C, index 2)
        "Healthspring": 3,   # Writing Broker Name (col D, index 3)
        "Wellable":     3,   # Writing Agent Name (col D, index 3)
    }
    col_idx = agent_col_map.get(carrier)
    if col_idx is None:
        return None

    # Find first non-empty agent name in data rows
    agent_name_raw = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        val = row[col_idx] if len(row) > col_idx else None
        if val and str(val).strip():
            agent_name_raw = str(val).strip()
            break

    if not agent_name_raw:
        return None

    normalized = _normalize_name(agent_name_raw)

    _NICKNAMES = {
        "michael": "mike", "mike": "michael",
        "christopher": "chris", "chris": "christopher",
        "timothy": "tim", "tim": "timothy",
        "william": "bill", "bill": "william",
        "robert": "bob", "bob": "robert",
        "richard": "rick", "rick": "richard",
        "james": "jim", "jim": "james",
        "thomas": "tom", "tom": "thomas",
    }

    def _first_matches(a, b):
        return a == b or _NICKNAMES.get(a) == b or _NICKNAMES.get(b) == a

    users = User.query.all()
    # Exact match after normalisation
    for user in users:
        if _normalize_name(user.name) == normalized:
            return user.id

    # Fuzzy: same last name + first name matches via nickname or prefix
    np = normalized.split()
    for user in users:
        up = _normalize_name(user.name).split()
        if len(np) >= 2 and len(up) >= 2 and np[-1] == up[-1]:
            if _first_matches(np[0], up[0]) or np[0][:3] == up[0][:3]:
                return user.id

    return None


PARSERS = {
    "UHC":         _parse_uhc,
    "Aetna":       _parse_aetna,
    "Humana":      _parse_humana,
    "BCBS":        _parse_bcbs,
    "Devoted":     _parse_devoted,
    "Healthspring": _parse_healthspring,
    "Wellable":    _parse_wellable,
}


def _enrich_line_items_with_commission_type(statements, agency_id):
    """
    For each statement's line items, look up commission_type from Policy by MBI.
    Mutates items in place, adding 'commission_type' key where a match exists.
    """
    all_mbis = set()
    for s in statements:
        for item in s.line_items_parsed:
            mbi = item.get('mbi', '').strip()
            if mbi:
                all_mbis.add(mbi)
    if not all_mbis:
        return
    rows = (Policy.query
            .filter(Policy.mbi.in_(all_mbis), Policy.agency_id == agency_id)
            .with_entities(Policy.mbi, Policy.commission_type)
            .all())
    mbi_to_type = {r.mbi: r.commission_type for r in rows if r.commission_type}
    for s in statements:
        for item in s.line_items_parsed:
            mbi = item.get('mbi', '').strip()
            if mbi and mbi in mbi_to_type:
                item['commission_type'] = mbi_to_type[mbi]


@commission_bp.route("/commissions")
@login_required
def commission_index():
    statements = (CommissionStatement.query
                  .filter_by(agent_id=current_user.id, agency_id=current_user.agency_id)
                  .order_by(CommissionStatement.statement_date.desc())
                  .all())
    for s in statements:
        s.line_items_parsed = json.loads(s.line_items) if s.line_items else []
    _enrich_line_items_with_commission_type(statements, current_user.agency_id)
    return render_template("commission.html",
        statements=statements, is_admin=False, viewing_agent=None)


@commission_bp.route("/admin/commissions")
@login_required
def commission_admin():
    if not current_user.is_admin:
        abort(403)
    agents = (User.query
              .filter(User.email != "admin@foundersinsuranceagency.com")
              .order_by(User.name).all())
    agency_id = current_user.agency_id
    agent_summaries = []
    for agent in agents:
        stmts = (CommissionStatement.query
                 .filter_by(agent_id=agent.id, agency_id=agency_id)
                 .order_by(CommissionStatement.statement_date.desc())
                 .limit(5).all())
        agent_summaries.append({"agent": agent, "statements": stmts})
    recent = (CommissionStatement.query
              .filter_by(agency_id=agency_id)
              .order_by(CommissionStatement.upload_date.desc())
              .limit(20).all())
    return render_template("commission.html",
        agent_summaries=agent_summaries, recent=recent,
        is_admin=True, viewing_agent=None)


@commission_bp.route("/admin/commissions/upload", methods=["POST"])
@login_required
def commission_upload():
    if not current_user.is_admin:
        abort(403)
    file = request.files.get("file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("commission.commission_admin"))

    try:
        file_bytes = file.read()
        filename_lower = (file.filename or "").lower()
        if filename_lower.endswith(".csv"):
            wb = _csv_bytes_to_workbook(file_bytes)
        else:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
    except Exception as e:
        flash(f"Could not read file: {e}", "error")
        return redirect(url_for("commission.commission_admin"))

    carrier = _detect_carrier(ws)
    if not carrier:
        flash("Could not detect carrier. Check column headers.", "error")
        return redirect(url_for("commission.commission_admin"))

    try:
        gross, bonus, paid, stmt_date, line_items, stated_rate = PARSERS[carrier](ws)
    except Exception as e:
        current_app.logger.error(f"Commission parse error ({carrier}): {e}")
        flash(f"Parse error for {carrier}: {e}", "error")
        return redirect(url_for("commission.commission_admin"))

    # 1. Try to get statement month from admin's manual override in the form
    form_month = request.form.get("statement_month", "").strip()  # format: "YYYY-MM"
    if form_month:
        try:
            stmt_date = datetime.strptime(form_month, "%Y-%m").date()
        except ValueError:
            pass

    # 2. Fall back to date parsed from file content
    # (already set by parser if it found a date in the file)

    # 3. Try to extract from filename
    if not stmt_date:
        stmt_date = _parse_date_from_filename(file.filename)

    # 4. Last resort: today (admin will see the period_label and can re-upload with override)
    if not stmt_date:
        stmt_date = date.today()
        flash(
            "Could not detect statement period from file content or filename. "
            "Defaulted to today's month. Use the 'Statement Month' field to correct this.",
            "warning"
        )

    # Aetna pays the agency directly across multiple LOA agents \u2014 no single portal user owns it.
    # Use agent_id=None (agency-level statement) and look up split from any active Aetna contract.
    AGENCY_LEVEL_CARRIERS = {"Aetna"}

    if carrier in AGENCY_LEVEL_CARRIERS:
        agent_id = None
        contract = AgentCarrierContract.query.filter_by(
            carrier=carrier, is_active=True
        ).first()
        agent_split = contract.split_rate if contract else 0.55
    else:
        # Auto-detect agent from file
        agent_id = _detect_agent_id(ws, carrier)
        if not agent_id:
            flash("Could not match agent name in file to a portal user. Check the Writing Agent Name column.", "error")
            return redirect(url_for("commission.commission_admin"))

        # Validate agent has active contract with this carrier
        contract = AgentCarrierContract.query.filter_by(
            agent_id=agent_id, carrier=carrier, is_active=True
        ).first()
        if not contract:
            agent_name = User.query.get(agent_id).display_name
            flash(f"\u26a0 {agent_name} does not have an active {carrier} contract. Upload rejected.", "error")
            return redirect(url_for("commission.commission_admin"))

        # Use agent's actual split rate
        agent_split = contract.split_rate
    period_label = stmt_date.strftime("%B %Y")
    expected     = round((gross + bonus) * agent_split, 2)
    # If the file has no summary row (paid=0), assume expected was paid — no discrepancy to flag.
    # AJ can adjust manually if the actual payment differs.
    if paid == 0.0:
        paid = expected
    difference   = round(expected - paid, 2)
    status       = "verified" if abs(difference) < 0.02 else "discrepancy"

    # Rate discrepancy check — flag when AJ's formula uses a different rate than the contract
    if stated_rate is not None and abs(stated_rate - agent_split) > 0.001:
        stated_pct  = round(stated_rate * 100, 2)
        contract_pct = round(agent_split * 100, 2)
        wrong_expected = round((gross + bonus) * stated_rate, 2)
        rate_diff = round(wrong_expected - expected, 2)
        direction = "underpaid" if rate_diff < 0 else "overpaid"
        flash(
            f"⚠ Rate mismatch on {carrier} {period_label}: AJ's file used {stated_pct}% "
            f"but contract rate is {contract_pct}%. "
            f"This would have {direction} by "
            f"${abs(rate_diff):,.2f}. Portal calculated expected at {contract_pct}%.",
            "warning"
        )

    existing = CommissionStatement.query.filter_by(
        carrier=carrier, agent_id=agent_id, period_label=period_label,
        agency_id=current_user.agency_id).first()
    _was_update = existing is not None
    if _was_update:
        flash(
            f"{carrier} {period_label} was already uploaded. "
            "Re-uploading will overwrite the existing statement and payment ledger rows.",
            "warning"
        )
    stmt = existing or CommissionStatement(
        carrier=carrier, agent_id=agent_id, agency_id=current_user.agency_id)
    if not existing:
        db.session.add(stmt)

    stmt.statement_date  = stmt_date
    stmt.period_label    = period_label
    stmt.gross_amount    = round(gross + bonus, 2)
    stmt.bonus_amount    = round(bonus, 2)
    stmt.split_rate      = agent_split
    stmt.expected_amount = expected
    stmt.paid_amount     = round(paid, 2)
    stmt.difference      = difference
    stmt.status          = status
    stmt.line_items      = json.dumps(line_items)
    stmt.filename        = file.filename
    stmt.uploaded_by_id  = current_user.id
    db.session.flush()   # get stmt.id before building payments

    # If re-uploading, clear stale payment ledger rows for this statement
    if _was_update:
        PolicyPayment.query.filter_by(
            statement_id=stmt.id, agency_id=current_user.agency_id
        ).delete(synchronize_session=False)
        db.session.flush()

    # Re-parse worksheet for payment ledger (ws cursor is already at start of data)
    wb2  = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws2  = wb2.active
    n_payments = build_payments(stmt, carrier, agent_id,
                                current_user.agency_id, ws2)
    db.session.commit()

    split_pct = round(agent_split * 100, 2)
    if status == "verified":
        flash(f"✓ {carrier} {period_label} — verified. Gross ${stmt.gross_amount:,.2f} × {split_pct}% = ${expected:,.2f} ✅", "success")
    else:
        flash(f"⚠ {carrier} {period_label} — discrepancy of ${abs(difference):,.2f}. Expected ${expected:,.2f} ({split_pct}%), paid ${paid:,.2f}.", "warning")

    return redirect(url_for("commission.commission_admin"))


@commission_bp.route("/admin/commissions/<int:stmt_id>/delete", methods=["POST"])
@login_required
def commission_delete(stmt_id):
    """Admin deletes a commission statement and all its payment ledger rows."""
    if not current_user.is_admin:
        abort(403)
    stmt = CommissionStatement.query.filter_by(
        id=stmt_id, agency_id=current_user.agency_id).first_or_404()
    label = f"{stmt.carrier} {stmt.period_label}"
    PolicyPayment.query.filter_by(
        statement_id=stmt.id, agency_id=current_user.agency_id
    ).delete(synchronize_session=False)
    db.session.delete(stmt)
    db.session.commit()
    flash(f"{label} statement deleted.", "success")
    return redirect(url_for("commission.commission_admin"))


@commission_bp.route("/admin/commissions/agent/<int:agent_id>")
@login_required
def commission_agent_detail(agent_id):
    if not current_user.is_admin:
        abort(403)
    agent = User.query.get_or_404(agent_id)
    statements = (CommissionStatement.query
                  .filter_by(agent_id=agent_id, agency_id=current_user.agency_id)
                  .order_by(CommissionStatement.statement_date.desc())
                  .all())
    for s in statements:
        s.line_items_parsed = json.loads(s.line_items) if s.line_items else []
    _enrich_line_items_with_commission_type(statements, current_user.agency_id)
    return render_template("commission.html",
        statements=statements, is_admin=True, viewing_agent=agent)


# ── Payment ledger ────────────────────────────────────────────────────────────

@commission_bp.route("/commissions/ledger")
@login_required
def commission_ledger():
    """Per-member payment ledger — agent view."""
    from sqlalchemy import func as sqlfunc

    agency_id = current_user.agency_id
    agent_id  = current_user.id

    # Available periods for this agent
    periods = (db.session.query(PolicyPayment.period_label, PolicyPayment.statement_date)
               .filter_by(agent_id=agent_id, agency_id=agency_id)
               .distinct()
               .order_by(PolicyPayment.statement_date.desc())
               .all())

    selected_period = request.args.get("period") or (periods[0].period_label if periods else None)
    carrier_filter  = request.args.get("carrier", "all")
    action_filter   = request.args.get("action",  "all")

    payments = []
    carriers = []
    summary  = {}

    if selected_period:
        q = (PolicyPayment.query
             .filter_by(agent_id=agent_id, agency_id=agency_id,
                        period_label=selected_period))
        if carrier_filter != "all":
            q = q.filter_by(carrier=carrier_filter)
        if action_filter != "all":
            q = q.filter_by(commission_action=action_filter)

        payments = q.order_by(PolicyPayment.carrier, PolicyPayment.member_name).all()

        # Summary stats for selected period (all carriers, unfiltered)
        all_period = (PolicyPayment.query
                      .filter_by(agent_id=agent_id, agency_id=agency_id,
                                 period_label=selected_period)
                      .all())
        total_paid      = sum(p.paid_amount for p in all_period)
        total_members   = len([p for p in all_period if not p.is_chargeback])
        total_chargebacks = sum(p.paid_amount for p in all_period if p.is_chargeback)
        unmatched_count = sum(1 for p in all_period if p.match_confidence == "unmatched")
        carriers = sorted(set(p.carrier for p in all_period))

        summary = {
            "total_paid":        total_paid,
            "total_members":     total_members,
            "total_chargebacks": total_chargebacks,
            "unmatched_count":   unmatched_count,
            "net_paid":          total_paid + total_chargebacks,
        }

    return render_template("commission_ledger.html",
        periods=periods,
        selected_period=selected_period,
        carrier_filter=carrier_filter,
        action_filter=action_filter,
        payments=payments,
        carriers=carriers,
        summary=summary,
        is_admin=False,
        viewing_agent=None,
    )


@commission_bp.route("/admin/commissions/ledger")
@login_required
def commission_ledger_admin():
    """Per-member payment ledger — admin view, all agents."""
    if not current_user.is_admin:
        abort(403)

    agency_id    = current_user.agency_id
    agent_id_arg = request.args.get("agent_id", type=int)

    agents = (User.query
              .filter(User.email != "admin@foundersinsuranceagency.com",
                      User.agency_id == agency_id)
              .order_by(User.name).all())

    selected_agent_id = agent_id_arg or (agents[0].id if agents else None)

    periods = []
    if selected_agent_id:
        periods = (db.session.query(PolicyPayment.period_label, PolicyPayment.statement_date)
                   .filter_by(agent_id=selected_agent_id, agency_id=agency_id)
                   .distinct()
                   .order_by(PolicyPayment.statement_date.desc())
                   .all())

    selected_period = request.args.get("period") or (periods[0].period_label if periods else None)
    carrier_filter  = request.args.get("carrier", "all")
    action_filter   = request.args.get("action",  "all")

    payments = []
    carriers = []
    summary  = {}

    if selected_period and selected_agent_id:
        q = (PolicyPayment.query
             .filter_by(agent_id=selected_agent_id, agency_id=agency_id,
                        period_label=selected_period))
        if carrier_filter != "all":
            q = q.filter_by(carrier=carrier_filter)
        if action_filter != "all":
            q = q.filter_by(commission_action=action_filter)

        payments = q.order_by(PolicyPayment.carrier, PolicyPayment.member_name).all()

        all_period = (PolicyPayment.query
                      .filter_by(agent_id=selected_agent_id, agency_id=agency_id,
                                 period_label=selected_period)
                      .all())
        total_paid        = sum(p.paid_amount for p in all_period)
        total_members     = len([p for p in all_period if not p.is_chargeback])
        total_chargebacks = sum(p.paid_amount for p in all_period if p.is_chargeback)
        unmatched_count   = sum(1 for p in all_period if p.match_confidence == "unmatched")
        carriers = sorted(set(p.carrier for p in all_period))

        summary = {
            "total_paid":        total_paid,
            "total_members":     total_members,
            "total_chargebacks": total_chargebacks,
            "unmatched_count":   unmatched_count,
            "net_paid":          total_paid + total_chargebacks,
        }

    return render_template("commission_ledger.html",
        periods=periods,
        selected_period=selected_period,
        carrier_filter=carrier_filter,
        action_filter=action_filter,
        payments=payments,
        carriers=carriers,
        summary=summary,
        is_admin=True,
        viewing_agent=User.query.get(selected_agent_id) if selected_agent_id else None,
        agents=agents,
        selected_agent_id=selected_agent_id,
    )


# ── Override workflow ──────────────────────────────────────────────────────────

@commission_bp.route("/admin/commissions/<int:stmt_id>/request-override", methods=["POST"])
@login_required
def commission_request_override(stmt_id):
    """Admin submits an explanation for a discrepancy and sends it to the agent for review."""
    if not current_user.is_admin:
        abort(403)
    stmt = CommissionStatement.query.filter_by(
        id=stmt_id, agency_id=current_user.agency_id).first_or_404()
    if stmt.status not in ("discrepancy",):
        flash("Override can only be requested on statements with a discrepancy.", "error")
        return redirect(url_for("commission.commission_admin"))

    note = request.form.get("override_note_admin", "").strip()
    if not note:
        flash("An explanation is required to submit for agent review.", "error")
        return redirect(url_for("commission.commission_admin"))

    stmt.override_note_admin     = note
    stmt.override_requested_by_id = current_user.id
    stmt.override_requested_at   = datetime.utcnow()
    stmt.override_note_agent     = None
    stmt.override_reviewed_by_id = None
    stmt.override_reviewed_at    = None
    stmt.status                  = "pending_review"
    db.session.commit()

    agent = User.query.get(stmt.agent_id)
    flash(f"Override sent to {agent.display_name} for review on {stmt.carrier} {stmt.period_label}.", "success")
    return redirect(url_for("commission.commission_admin"))


@commission_bp.route("/commissions/<int:stmt_id>/review-override", methods=["POST"])
@login_required
def commission_review_override(stmt_id):
    """Agent accepts or disputes an override submitted by admin."""
    stmt = CommissionStatement.query.filter_by(
        id=stmt_id, agent_id=current_user.id,
        agency_id=current_user.agency_id).first_or_404()
    if stmt.status != "pending_review":
        flash("This statement is not awaiting your review.", "error")
        return redirect(url_for("commission.commission_index"))

    action = request.form.get("action")   # "accept" or "dispute"
    note   = request.form.get("override_note_agent", "").strip()

    if action not in ("accept", "dispute"):
        flash("Invalid action.", "error")
        return redirect(url_for("commission.commission_index"))
    if action == "dispute" and not note:
        flash("Please provide your reasoning when disputing a discrepancy.", "error")
        return redirect(url_for("commission.commission_index"))

    stmt.override_note_agent     = note
    stmt.override_reviewed_by_id = current_user.id
    stmt.override_reviewed_at    = datetime.utcnow()
    stmt.status                  = "accepted" if action == "accept" else "disputed"
    db.session.commit()

    if action == "accept":
        flash(f"You accepted the {stmt.carrier} {stmt.period_label} override.", "success")
    else:
        flash(f"Your dispute on {stmt.carrier} {stmt.period_label} has been submitted to admin for review.", "warning")
    return redirect(url_for("commission.commission_index"))


@commission_bp.route("/admin/commissions/<int:stmt_id>/close-dispute", methods=["POST"])
@login_required
def commission_close_dispute(stmt_id):
    """Admin closes a disputed statement — marks it accepted after reviewing agent's note."""
    if not current_user.is_admin:
        abort(403)
    stmt = CommissionStatement.query.filter_by(
        id=stmt_id, agency_id=current_user.agency_id).first_or_404()
    if stmt.status != "disputed":
        flash("This statement is not in disputed status.", "error")
        return redirect(url_for("commission.commission_admin"))

    stmt.status = "accepted"
    db.session.commit()
    flash(f"{stmt.carrier} {stmt.period_label} dispute closed and marked accepted.", "success")
    return redirect(url_for("commission.commission_admin"))


# ─────────────────────────────────────────────
# Reconciliation helpers
# ─────────────────────────────────────────────

def _period_bounds(period_label):
    """Convert 'March 2026' to (date(2026,3,1), date(2026,3,31))."""
    try:
        start = datetime.strptime(period_label, "%B %Y").date().replace(day=1)
        end = start + relativedelta(months=1) - relativedelta(days=1)
        return start, end
    except (ValueError, TypeError):
        return None, None


def _reconcile(agency_id, agent_id, carrier, period_label):
    """Run both reconciliation queries for a single agent+carrier+period.
    Returns dict with 'unpaid_policies' and 'unmatched_payments'.
    """
    period_start, period_end = _period_bounds(period_label)
    if not period_start:
        return {'unpaid_policies': [], 'unmatched_payments': []}

    paid_policy_ids = (db.session.query(PolicyPayment.policy_id)
        .filter_by(agency_id=agency_id, agent_id=agent_id,
                   carrier=carrier, period_label=period_label)
        .filter(PolicyPayment.policy_id.isnot(None))
        .subquery())

    unpaid = (Policy.query
        .filter_by(agency_id=agency_id, agent_id=agent_id,
                   carrier=carrier, status='active')
        .filter(Policy.effective_date <= period_end)
        .filter(or_(Policy.term_date.is_(None), Policy.term_date > period_start))
        .filter(~Policy.id.in_(paid_policy_ids))
        .all())

    unmatched = (PolicyPayment.query
        .filter_by(agency_id=agency_id, agent_id=agent_id,
                   carrier=carrier, period_label=period_label,
                   match_confidence='unmatched')
        .all())

    return {'unpaid_policies': unpaid, 'unmatched_payments': unmatched}


# ─────────────────────────────────────────────
# Reconciliation routes
# ─────────────────────────────────────────────

@commission_bp.route('/commissions/reconciliation')
@login_required
def reconciliation_view():
    agency_id = current_user.agency_id
    agent_id = current_user.id

    available = (db.session.query(
            CommissionStatement.carrier,
            CommissionStatement.period_label,
        )
        .filter_by(agency_id=agency_id, agent_id=agent_id)
        .distinct()
        .order_by(CommissionStatement.period_label.desc(),
                  CommissionStatement.carrier.asc())
        .all())

    selected_carrier = request.args.get('carrier')
    selected_period = request.args.get('period')

    results = None
    if selected_carrier and selected_period:
        results = _reconcile(agency_id, agent_id, selected_carrier, selected_period)

    return render_template('commission_reconciliation.html',
        available=available,
        selected_carrier=selected_carrier,
        selected_period=selected_period,
        results=results,
        is_admin=False,
        agents=None,
        selected_agent_id=agent_id)


@commission_bp.route('/admin/commissions/reconciliation')
@login_required
def admin_reconciliation_view():
    if not current_user.is_admin:
        abort(403)
    agency_id = current_user.agency_id

    agents = User.query.filter_by(agency_id=agency_id).order_by(User.email).all()

    selected_agent_id = request.args.get('agent_id', type=int) or current_user.id

    available = (db.session.query(
            CommissionStatement.carrier,
            CommissionStatement.period_label,
        )
        .filter_by(agency_id=agency_id, agent_id=selected_agent_id)
        .distinct()
        .order_by(CommissionStatement.period_label.desc(),
                  CommissionStatement.carrier.asc())
        .all())

    selected_carrier = request.args.get('carrier')
    selected_period = request.args.get('period')

    results = None
    if selected_carrier and selected_period:
        results = _reconcile(agency_id, selected_agent_id, selected_carrier, selected_period)

    return render_template('commission_reconciliation.html',
        available=available,
        selected_carrier=selected_carrier,
        selected_period=selected_period,
        results=results,
        is_admin=True,
        agents=agents,
        selected_agent_id=selected_agent_id)
