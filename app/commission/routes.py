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
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    bonus = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        action     = str(row[4] or "").strip()
        commission = row[5]

        if stmt_date is None and row[0] and isinstance(row[0], datetime):
            stmt_date = row[0].date()

        # Skip summary rows — _scan_summary already handled them
        if re.search(r'[\d,]+\.?\d*\s*x\.?\s*\.?\d+', action):
            continue
        if re.search(r'^\$[\d,]+\.\d+\s*\+', action):
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

    return gross, bonus, paid or 0.0, stmt_date, line_items, stated_rate


def _parse_aetna(ws):
    paid, stated_rate = _scan_summary(ws)
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    line_items = []
    gross = 0.0
    stmt_date = None

    for row in rows:
        if not any(row):
            continue
        # Skip summary rows
        if re.search(r'[\d,]+\.?\d*\s*x', str(row[9] or "")):
            continue

        amount = row[10]  # Payee Amount
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
    stmt_date = date.today()

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

    if stmt_date is None:
        stmt_date = date.today()
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

    if stmt_date is None:
        stmt_date = date.today()
    return gross, 0.0, paid or 0.0, stmt_date, line_items, stated_rate


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
        "Aetna":        9,   # Writing Agent Name (col J, index 9)
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
        gross, bonus, paid, stmt_date, line_items, stated_rate = PARSERS[carrier](ws)
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

    split_pct = round(agent_split * 100, 2)
    if status == "verified":
        flash(f"✓ {carrier} {period_label} — verified. Gross ${stmt.gross_amount:,.2f} × {split_pct}% = ${expected:,.2f} ✅", "success")
    else:
        flash(f"⚠ {carrier} {period_label} — discrepancy of ${abs(difference):,.2f}. Expected ${expected:,.2f} ({split_pct}%), paid ${paid:,.2f}.", "warning")

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
