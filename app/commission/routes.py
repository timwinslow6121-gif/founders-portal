import io
import json
import re
from datetime import date, datetime

import openpyxl
from flask import (abort, flash, redirect, render_template,
                   request, url_for, current_app)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import CommissionStatement, User, AgentCarrierContract
from app.commission import commission_bp

SPLIT_RATE = 0.55


def _parse_uhc(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    bonus = 0.0
    paid  = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        action     = str(row[4] or "").strip()
        commission = row[5]

        if stmt_date is None and row[0] and isinstance(row[0], datetime):
            stmt_date = row[0].date()

        if re.search(r'[\d,]+\.?\d*\s*x\.?\s*\.?\d+', action):
            # Gross summary row e.g. "$7,566.59 x.55" — paid is on a separate row
            continue

        # Paid summary row e.g. "$4,161.62 + $130.81" with numeric paid in col 5
        if re.search(r'^\$[\d,]+\.\d+\s*\+\s*\$[\d,]+', action):
            if commission and isinstance(commission, (int, float)):
                paid = float(commission)
            continue

        if action.startswith("HA payment"):
            if commission and isinstance(commission, (int, float)):
                bonus += float(commission)
            continue

        if action in ("Renewal", "New"):
            amt = float(commission) if commission and isinstance(commission, (int, float)) else None
            if amt:
                gross += amt
            line_items.append({
                "member":      str(row[2] or ""),
                "eff_date":    str(row[3].date() if isinstance(row[3], datetime) else row[3] or ""),
                "action":      action,
                "amount":      amt,
                "term_reason": str(row[6] or ""),
            })

    return gross, bonus, paid, stmt_date, line_items


def _parse_aetna(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    paid  = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Summary row: "202.44 x.525" is in col 9 (Writing Agent Name col), paid in col 10
        col9 = str(row[9] or "").strip()
        if re.search(r'[\d,]+\.?\d*\s*x', col9):
            if row[10] and isinstance(row[10], (int, float)):
                paid = float(row[10])
            continue

        amount = row[10]  # Payee Amount is col 10 (index 10)
        if stmt_date is None and row[7] and isinstance(row[7], datetime):
            stmt_date = row[7].date()

        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            line_items.append({
                "member":   str(row[3] or ""),
                "plan":     str(row[6] or ""),
                "eff_date": str(row[7].date() if isinstance(row[7], datetime) else row[7] or ""),
                "action":   str(row[5] or ""),
                "amount":   float(amount),
            })

    return gross, 0.0, paid, stmt_date, line_items


def _parse_humana(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross      = 0.0
    paid       = 0.0
    stmt_date  = None

    for row in rows:
        if not any(row):
            continue
        # Summary row check (not present in all Humana files — skip if found)
        col8 = str(row[8] or "").strip()
        if re.search(r'[\$\d,]+\.?\d*\s*x', col8):
            if row[9] and isinstance(row[9], (int, float)):
                paid = float(row[9])
            continue

        amount  = row[8]   # PaidAmount is col I (index 8)
        comment = str(row[9] or "").strip()

        if stmt_date is None and row[1] and isinstance(row[1], datetime):
            stmt_date = row[1].date()

        if amount and isinstance(amount, (int, float)):
            gross += float(amount)  # net all rows — chargebacks are negative
            line_items.append({
                "member":  str(row[4] or ""),   # GrpName
                "month":   str(row[6] or ""),   # MonthPaid
                "action":  comment,             # Comment (e.g. RENEWAL COMMISSIONS)
                "amount":  float(amount),
                "product": str(row[7] or ""),   # Product
            })

    # Humana pays net — paid = gross (no separate paid row)
    paid = gross
    return gross, 0.0, paid, stmt_date, line_items


def _parse_bcbs(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    paid  = 0.0
    stmt_date = date.today()

    for row in rows:
        if not any(row):
            continue
        # Summary row: "$846.88 x .55" in col 9 (Premium Period), paid in col 10
        col9 = str(row[9] or "").strip()
        if re.search(r'[\$\d,]+\.?\d*\s*x', col9):
            if row[10] and isinstance(row[10], (int, float)):
                paid = float(row[10])
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

    return gross, 0.0, paid, stmt_date, line_items


def _parse_devoted(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    bonus = 0.0
    paid  = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Summary row: "347 x .55" in col 8 (Disenroll Date col), paid in col 9
        col8 = str(row[8] or "").strip()
        if re.search(r'[\$\d,]+\s*x\.?\s*\.?\d+', col8):
            if row[9] and isinstance(row[9], (int, float)):
                paid = float(row[9])
            continue

        amount = row[11]  # Base Amount is index 11
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

    return gross, bonus, paid, stmt_date, line_items


def _parse_healthspring(ws):
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    paid  = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Summary row: col 6 (Pay Period col) contains "NNN x.55", col 7 is the paid amount
        col6 = str(row[6] if len(row) > 6 else "").strip()
        if re.search(r'[\d,]+\s*x\.?\s*\.?\d+', col6):
            if row[7] and isinstance(row[7], (int, float)):
                paid = float(row[7])
            continue

        amount = row[7] if len(row) > 7 else None
        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            pay_period = row[6]
            if stmt_date is None and isinstance(pay_period, datetime):
                stmt_date = pay_period.date()
            line_items.append({
                "member":      str(row[8] or ""),   # Member ID
                "mbi":         str(row[9] or ""),   # MBI
                "action":      str(row[0] or ""),   # Payment Type
                "description": str(row[1] or ""),   # Payment Description
                "amount":      float(amount),
            })

    if stmt_date is None:
        stmt_date = date.today()
    return gross, 0.0, paid, stmt_date, line_items


def _parse_wellable(ws):
    """Wellable advance commissions — flagged as clawback-eligible advances."""
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    paid  = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Summary row: col 16 (Advance Type col) contains "NNN x .55"
        col16 = str(row[16] if len(row) > 16 else "").strip()
        if re.search(r'[\$\d,]+\.?\d*\s*x\s*\.?\d+', col16):
            if row[17] and isinstance(row[17], (int, float)):
                paid = float(row[17])
            continue

        advance_amount = row[16] if len(row) > 16 else None
        if advance_amount and isinstance(advance_amount, (int, float)):
            gross += float(advance_amount)
            app_date = row[17] if len(row) > 17 else None
            if stmt_date is None and isinstance(app_date, datetime):
                stmt_date = app_date.date()
            line_items.append({
                "member":        str(row[5] or ""),   # Insured Name
                "policy":        str(row[4] or ""),   # Policy number
                "plan":          str(row[7] or ""),   # Plan Code
                "premium":       float(row[12]) if row[12] else 0.0,
                "advance_pct":   float(row[13]) if row[13] else 0.0,
                "advance_months": str(row[14] or ""),
                "action":        str(row[15] or ""),  # Advance Type (e.g. "1st Year Advance")
                "amount":        float(advance_amount),
                "is_advance":    True,                # clawback flag
            })

    if stmt_date is None:
        stmt_date = date.today()
    return gross, 0.0, paid, stmt_date, line_items


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
        "UHC":          1,   # Writing Agent Name (col B, index 1)
        "Aetna":        8,   # Writing Agent Name (col I, index 8)
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

    # Match against all users
    users = User.query.all()
    for user in users:
        if _normalize_name(user.name) == normalized:
            return user.id

    # Fuzzy fallback — check if normalized name is contained in user name
    for user in users:
        user_norm = _normalize_name(user.name)
        if normalized in user_norm or user_norm in normalized:
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


@commission_bp.route("/commissions")
@login_required
def commission_index():
    statements = (CommissionStatement.query
                  .filter_by(agent_id=current_user.id, agency_id=current_user.agency_id)
                  .order_by(CommissionStatement.statement_date.desc())
                  .all())
    for s in statements:
        s.line_items_parsed = json.loads(s.line_items) if s.line_items else []
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
        wb = openpyxl.load_workbook(io.BytesIO(file.read()), data_only=True)
        ws = wb.active
    except Exception as e:
        flash(f"Could not read file: {e}", "error")
        return redirect(url_for("commission.commission_admin"))

    carrier = _detect_carrier(ws)
    if not carrier:
        flash("Could not detect carrier. Check column headers.", "error")
        return redirect(url_for("commission.commission_admin"))

    try:
        gross, bonus, paid, stmt_date, line_items = PARSERS[carrier](ws)
    except Exception as e:
        current_app.logger.error(f"Commission parse error ({carrier}): {e}")
        flash(f"Parse error for {carrier}: {e}", "error")
        return redirect(url_for("commission.commission_admin"))

    if not stmt_date:
        stmt_date = date.today()

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
    agent_split  = contract.split_rate
    period_label = stmt_date.strftime("%B %Y")
    expected     = round((gross + bonus) * agent_split, 2)
    difference   = round(expected - paid, 2)
    status       = "verified" if abs(difference) < 0.02 else "discrepancy"

    existing = CommissionStatement.query.filter_by(
        carrier=carrier, agent_id=agent_id, period_label=period_label,
        agency_id=current_user.agency_id).first()
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
    db.session.commit()

    if status == "verified":
        flash(f"✓ {carrier} {period_label} — verified. Gross ${stmt.gross_amount:,.2f} × 55% = ${expected:,.2f} ✅", "success")
    else:
        flash(f"⚠ {carrier} {period_label} — discrepancy of ${abs(difference):,.2f}. Expected ${expected:,.2f}, paid ${paid:,.2f}.", "warning")

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
    return render_template("commission.html",
        statements=statements, is_admin=True, viewing_agent=agent)
