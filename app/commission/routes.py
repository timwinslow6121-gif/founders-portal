import io
import json
import re
from datetime import date, datetime

import openpyxl
from flask import (abort, flash, redirect, render_template,
                   request, url_for, current_app)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import CommissionStatement, User
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
        col11 = str(row[11] or "").strip()
        if re.search(r'[\d,]+\.?\d*\s*x', col11):
            if row[12] and isinstance(row[12], (int, float)):
                paid = float(row[12])
            continue

        amount = row[12]
        if stmt_date is None and row[0] and isinstance(row[0], datetime):
            stmt_date = row[0].date()

        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            line_items.append({
                "member":   str(row[1] or ""),
                "plan_id":  str(row[3] or ""),
                "eff_date": str(row[6].date() if isinstance(row[6], datetime) else row[6] or ""),
                "action":   str(row[2] or ""),
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
        col4 = str(row[4] or "").strip()
        if re.search(r'[\$\d,]+\.?\d*\s*x', col4):
            if row[5] and isinstance(row[5], (int, float)):
                paid = float(row[5])
            continue

        amount  = row[5]
        comment = str(row[6] or "").strip()

        if stmt_date is None and row[0] and isinstance(row[0], datetime):
            stmt_date = row[0].date()

        if amount and isinstance(amount, (int, float)):
            gross += float(amount)  # net all rows — chargebacks are negative
            line_items.append({
                "member":   str(row[2] or ""),
                "month":    str(row[4] or ""),
                "action":   comment,
                "amount":   float(amount),
                "txn_type": str(row[9] or ""),
                "eff_date": str(row[10].date() if isinstance(row[10], datetime) else row[10] or ""),
            })

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
        col11 = str(row[11] or "").strip()
        if re.search(r'[\$\d,]+\.?\d*\s*x', col11):
            if row[12] and isinstance(row[12], (int, float)):
                paid = float(row[12])
            continue
        col13 = str(row[13] or "").strip()
        if col13.startswith("="):
            continue
        col12 = str(row[12] or "").strip()
        if col12.lower() == "total:":
            continue

        commission = row[13]
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
        col2 = str(row[2] or "").strip()
        col3 = str(row[3] or "").strip()

        if re.search(r'[\$\d,]+\s*x\.?\s*\.?\d+', col2):
            # Summary row — col2 has bonus "e.g. $1,100 x.55"
            # col3 has total paid "e.g. 605 + 4,389.55 = $4,994.55"
            bonus_match = re.search(r'\$?([\d,]+)', col2)
            if bonus_match:
                bonus += float(bonus_match.group(1).replace(',', ''))
            # Extract paid from col3 on the same row
            paid_match = re.search(r'=\s*\$?([\d,]+\.?\d*)', col3)
            if paid_match:
                paid = float(paid_match.group(1).replace(',', ''))
            continue

        amount = row[10]
        if amount and isinstance(amount, (int, float)):
            gross += float(amount)
            line_items.append({
                "member":    f"{row[5] or ''} {row[6] or ''}".strip(),
                "member_id": str(row[3] or ""),
                "eff_date":  str(row[8] or ""),
                "period":    str(row[9] or ""),
                "action":    "New/Renewal",
                "amount":    float(amount),
            })

        if stmt_date is None and row[0]:
            try:
                stmt_date = datetime.strptime(str(row[0]), "%m/%d/%Y").date()
            except Exception:
                pass

    return gross, bonus, paid, stmt_date, line_items


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
        "UHC":     1,   # Writing Agent Name (col B, index 1)
        "Aetna":   8,   # Writing Agent Name (col I, index 8)
        "Humana":  1,   # WaName (col B, index 1)
        "BCBS":    1,   # Agent Name (col B, index 1)
        "Devoted": 2,   # Agent Name (col C, index 2)
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
    "UHC":     _parse_uhc,
    "Aetna":   _parse_aetna,
    "Humana":  _parse_humana,
    "BCBS":    _parse_bcbs,
    "Devoted": _parse_devoted,
}


@commission_bp.route("/commissions")
@login_required
def commission_index():
    statements = (CommissionStatement.query
                  .filter_by(agent_id=current_user.id)
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
    agent_summaries = []
    for agent in agents:
        stmts = (CommissionStatement.query
                 .filter_by(agent_id=agent.id)
                 .order_by(CommissionStatement.statement_date.desc())
                 .limit(5).all())
        agent_summaries.append({"agent": agent, "statements": stmts})
    recent = (CommissionStatement.query
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

    period_label    = stmt_date.strftime("%B %Y")
    expected        = round((gross + bonus) * SPLIT_RATE, 2)
    difference      = round(expected - paid, 2)
    status          = "verified" if abs(difference) < 0.02 else "discrepancy"

    # Auto-detect agent from file
    agent_id = _detect_agent_id(ws, carrier)
    if not agent_id:
        flash(f"Could not match agent name in file to a portal user. Check the Writing Agent Name column.", "error")
        return redirect(url_for("commission.commission_admin"))

    existing = CommissionStatement.query.filter_by(
        carrier=carrier, agent_id=agent_id, period_label=period_label).first()
    stmt = existing or CommissionStatement(carrier=carrier, agent_id=agent_id)
    if not existing:
        db.session.add(stmt)

    stmt.statement_date  = stmt_date
    stmt.period_label    = period_label
    stmt.gross_amount    = round(gross + bonus, 2)
    stmt.bonus_amount    = round(bonus, 2)
    stmt.split_rate      = SPLIT_RATE
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
                  .filter_by(agent_id=agent_id)
                  .order_by(CommissionStatement.statement_date.desc())
                  .all())
    for s in statements:
        s.line_items_parsed = json.loads(s.line_items) if s.line_items else []
    return render_template("commission.html",
        statements=statements, is_admin=True, viewing_agent=agent)
