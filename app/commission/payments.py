"""
app/commission/payments.py

Builds PolicyPayment rows from parsed commission statement line items.
Called from commission_upload() after the statement is saved.

Matching priority per carrier:
  1. Full MBI    (Aetna col0, Healthspring col9)
  2. Carrier ID  (Devoted member_id, Wellable policy number)
  3. Fuzzy name  (UHC, Humana, BCBS — last+first normalized)

commission_action normalisation (canonical values):
  'renewal'    — monthly renewal payment
  'initial'    — first-year / new enrollment payment
  'hra_bonus'  — health risk assessment bonus
  'chargeback' — negative / clawback row
  'advance'    — Wellable advance (clawback-eligible)
  'other'      — anything else
"""

import re
from datetime import datetime

from app.extensions import db
from app.models import PolicyPayment, Policy


# ── Name normalisation ─────────────────────────────────────────────────────────

def _norm(s):
    """'WINSLOW, TIMOTHY JAMES' / 'TIMOTHY WINSLOW' / 'WINSLOW TIMOTHY J' → 'timothy winslow'"""
    s = str(s or "").strip().lower()
    s = re.sub(r'\s+', ' ', s)
    if not s:
        return ""
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        last  = parts[0]
        first = parts[1].split()[0] if parts[1].strip() else ""
        return f"{first} {last}".strip()
    words = s.split()
    if len(words) <= 2:
        return s
    # "winslow timothy j" → "timothy winslow"
    return f"{words[1]} {words[0]}".strip()


# ── Action normalisation ───────────────────────────────────────────────────────

def _norm_action(raw, amount=None):
    """Map carrier-specific action strings to canonical commission_action values."""
    r = str(raw or "").lower().strip()
    amt = float(amount or 0)

    if amt < 0:
        return "chargeback"
    if "rapid" in r or "disenroll" in r:
        return "chargeback"
    if "advance" in r:
        return "advance"
    if "hra" in r or r.startswith("ha ") or r.startswith("ha payment"):
        return "hra_bonus"
    if r in ("renewal", "renew") or "renewal" in r:
        return "renewal"
    if r in ("new", "initial") or "new" in r or "initial" in r or "first year" in r:
        return "initial"
    if "fy" == r:
        return "initial"
    if "cms new" == r:
        return "initial"
    return "other"


# ── Per-carrier line-item extractors ──────────────────────────────────────────

def _parse_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                pass
    return None


def extract_uhc(rows):
    """
    UHC columns:
      0 Statement Date, 1 Writing Agent Name, 2 Member Name,
      3 Original Effective Date, 4 Commission Action, 5 Commission,
      6 Term Reason, 7 Term Date
    HA rows: action = "HA payment for agent... member NAME MBI *****XXXX policy number NNN"
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        action_raw = str(row[4] or "").strip()
        amount     = row[5]

        if not isinstance(amount, (int, float)):
            continue

        # Skip AJ's summary rows
        if re.search(r'[\d,]+\.?\d*\s*x\.?\s*\.?\d+', action_raw):
            continue
        if re.search(r'^\$[\d,]+\.\d+\s*\+', action_raw):
            continue

        # HA bonus rows — member name and partial MBI embedded in action string
        if action_raw.lower().startswith("ha payment"):
            m_name = re.search(r'member\s+([A-Z][A-Z\s]+?)\s+MBI', action_raw)
            m_mbi  = re.search(r'MBI\s+\*+(\w+)', action_raw)
            items.append({
                "member_name":       m_name.group(1).strip() if m_name else "HA BONUS",
                "mbi":               None,
                "carrier_member_id": None,
                "action_raw":        action_raw,
                "commission_action": "hra_bonus",
                "paid_amount":       float(amount),
                "effective_date":    None,
                "term_date":         None,
                "term_reason":       None,
                "period_month":      None,
                "plan_name":         None,
            })
            continue

        if action_raw not in ("Renewal", "New"):
            continue

        items.append({
            "member_name":       str(row[2] or ""),
            "mbi":               None,
            "carrier_member_id": None,
            "action_raw":        action_raw,
            "commission_action": _norm_action(action_raw, amount),
            "paid_amount":       float(amount),
            "effective_date":    _parse_date(row[3]),
            "term_date":         _parse_date(row[7]),
            "term_reason":       str(row[6] or "") or None,
            "period_month":      None,
            "plan_name":         None,
        })
    return items


def extract_aetna(rows):
    """
    Aetna April 2026 column layout (0-indexed):
      0  Payment Date       1  Medicare Number (MBI)   2  Member ID
      4  Member Name        6  Sales Event             7  Product
      9  Plan ID            12 Effective Date          14 Writing Agent NPN
      16 Writing Agent Name 20 Payee Amount            21 CMS New
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        # Skip footer rows ("Total Payee Amount: ...")
        if str(row[0] or "").strip().lower().startswith("total"):
            continue

        amount = row[20]
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", "").replace("$", "").strip())
            except ValueError:
                continue
        if not isinstance(amount, (int, float)):
            continue

        cms_new    = str(row[21] or "").strip().upper()
        action_raw = str(row[6] or "").strip()
        if cms_new == "Y":
            action_raw = "initial"

        items.append({
            "member_name":        str(row[4] or ""),
            "mbi":                str(row[1] or "").strip() or None,
            "carrier_member_id":  str(row[2] or "").strip() or None,
            "action_raw":         action_raw,
            "commission_action":  _norm_action(action_raw, amount),
            "paid_amount":        float(amount),
            "effective_date":     _parse_date(row[12]),
            "term_date":          None,
            "term_reason":        None,
            "period_month":       None,
            "plan_name":          str(row[9] or "") or None,
            "writing_agent_name": str(row[16] or "").strip() or None,
        })
    return items


def extract_humana(rows):
    """
    Humana columns:
      0 AorSan, 1 CommRunDt, 2 WaName, 3 WaSan, 4 GrpName (member name),
      5 TxnDueDt, 6 MonthPaid, 7 Product, 8 PaidAmount, 9 Comment
    No MBI — name matching only.
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        if re.search(r'[\$\d,]+\.?\d*\s*x', str(row[8] or "")):
            continue

        amount = row[8]
        if not isinstance(amount, (int, float)):
            continue

        comment    = str(row[9] or "").strip()
        action_raw = comment

        items.append({
            "member_name":       str(row[4] or ""),
            "mbi":               None,
            "carrier_member_id": None,
            "action_raw":        action_raw,
            "commission_action": _norm_action(action_raw, amount),
            "paid_amount":       float(amount),
            "effective_date":    _parse_date(row[5]),
            "term_date":         None,
            "term_reason":       None,
            "period_month":      str(row[6] or "") or None,
            "plan_name":         str(row[7] or "") or None,
        })
    return items


def extract_bcbs(rows):
    """
    BCBS columns:
      0 Agent #, 1 Agent Name, 2 Group Type (FY/RENEW), 3 Customer Name,
      4 Customer No, 5 ORIGEFFDATE, 6 Product, 7 COVERAGEFROM,
      9 Premium Period, 12 Billed Amount, 13 Commission
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        if re.search(r'[\$\d,]+\.?\d*\s*x', str(row[9] or "")):
            continue
        if len(row) <= 13:
            continue

        commission = row[13]
        if not isinstance(commission, (int, float)) or float(commission) == 0:
            continue

        group_type = str(row[2] or "").strip()
        action_raw = group_type  # FY or RENEW

        items.append({
            "member_name":       str(row[3] or ""),
            "mbi":               None,
            "carrier_member_id": str(row[4] or "").strip() or None,
            "action_raw":        action_raw,
            "commission_action": _norm_action(action_raw, commission),
            "paid_amount":       float(commission),
            "effective_date":    _parse_date(row[5]),
            "term_date":         None,
            "term_reason":       None,
            "period_month":      None,
            "plan_name":         str(row[6] or "") or None,
        })
    return items


def extract_devoted(rows):
    """
    Devoted columns:
      0 Statement Date, 1 Agent NPN, 2 Agent Name, 3 Member ID,
      4 Member HICN, 5 Member First, 6 Member Last, 7 Effective Date,
      8 Disenroll Date, 9 Commission Type, 10 Period, 11 Base Amount
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        if re.search(r'[\$\d,]+\s*x\.?\s*\.?\d+', str(row[8] or "")):
            continue

        amount = row[11]
        if not isinstance(amount, (int, float)):
            continue

        member_name = f"{row[5] or ''} {row[6] or ''}".strip()
        action_raw  = str(row[9] or "")

        items.append({
            "member_name":       member_name,
            "mbi":               None,
            "carrier_member_id": str(row[3] or "").strip() or None,
            "action_raw":        action_raw,
            "commission_action": _norm_action(action_raw, amount),
            "paid_amount":       float(amount),
            "effective_date":    _parse_date(row[7]),
            "term_date":         _parse_date(row[8]),
            "term_reason":       None,
            "period_month":      str(row[10] or "") or None,
            "plan_name":         None,
        })
    return items


def extract_healthspring(rows):
    """
    Healthspring columns:
      0 Payment Type, 1 Payment Description, 2 Writing Broker NPN,
      3 Writing Broker Name, 4 Earner NPN, 5 Earner Name,
      6 Pay Period, 7 Payment Amount, 8 Member ID, 9 MBI
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        if re.search(r'[\d,]+\s*x\.?\s*\.?\d+', str(row[6] if len(row) > 6 else "")):
            continue

        amount = row[7] if len(row) > 7 else None
        if not isinstance(amount, (int, float)):
            continue

        action_raw = str(row[0] or "")

        items.append({
            "member_name":       str(row[8] or ""),
            "mbi":               str(row[9] or "").strip() or None,
            "carrier_member_id": str(row[8] or "").strip() or None,
            "action_raw":        action_raw,
            "commission_action": _norm_action(action_raw, amount),
            "paid_amount":       float(amount),
            "effective_date":    _parse_date(row[6]),
            "term_date":         None,
            "term_reason":       None,
            "period_month":      None,
            "plan_name":         None,
        })
    return items


def extract_wellable(rows):
    """
    Wellable columns:
      0 Company, 3 Writing Agent Name, 4 Policy, 5 Insured Name,
      6 Insured DOB, 7 Plan Code, 8 Issue Date, 14 Advance Type,
      15 Comments, 16 Advance Amount
    """
    items = []
    for row in rows:
        if not any(row):
            continue
        if re.search(r'[\$\d,]+\.?\d*\s*x\s*\.?\d+', str(row[16] if len(row) > 16 else "")):
            continue

        amount = row[16] if len(row) > 16 else None
        if not isinstance(amount, (int, float)):
            continue

        items.append({
            "member_name":       str(row[5] or ""),
            "mbi":               None,
            "carrier_member_id": str(row[4] or "").strip() or None,
            "action_raw":        str(row[15] or ""),
            "commission_action": "advance",
            "paid_amount":       float(amount),
            "effective_date":    _parse_date(row[8]),
            "term_date":         None,
            "term_reason":       None,
            "period_month":      None,
            "plan_name":         str(row[7] or "") or None,
        })
    return items


EXTRACTORS = {
    "UHC":          extract_uhc,
    "Aetna":        extract_aetna,
    "Humana":       extract_humana,
    "BCBS":         extract_bcbs,
    "Devoted":      extract_devoted,
    "Healthspring": extract_healthspring,
    "Wellable":     extract_wellable,
}


# ── Matching logic ─────────────────────────────────────────────────────────────

def _build_name_index(agency_id):
    """Build normalized name → policy_id lookup for fuzzy name matching."""
    policies = (Policy.query
                .filter_by(agency_id=agency_id, status="active")
                .with_entities(Policy.id, Policy.full_name, Policy.mbi, Policy.member_id, Policy.carrier)
                .all())
    name_map = {}
    for p in policies:
        norm = _norm(p.full_name)
        if norm:
            name_map.setdefault(norm, []).append(p)
    return name_map


def _match_policy(item, carrier, agency_id, mbi_map, carrier_id_map, name_map):
    """
    Try to match a line item dict to a Policy record.
    Returns (policy_id, match_confidence) or (None, 'unmatched').
    """
    # 1. Exact MBI match
    mbi = (item.get("mbi") or "").strip()
    if mbi and mbi in mbi_map:
        return mbi_map[mbi], "exact_mbi"

    # 2. Exact carrier member ID match (scoped to carrier)
    cid = (item.get("carrier_member_id") or "").strip()
    key = (carrier, cid)
    if cid and key in carrier_id_map:
        return carrier_id_map[key], "exact_carrier_id"

    # 3. Fuzzy name match — normalized "first last"
    norm = _norm(item.get("member_name", ""))
    if norm and norm in name_map:
        candidates = name_map[norm]
        # Prefer same carrier
        for p in candidates:
            if p.carrier == carrier:
                return p.id, "fuzzy_name"
        return candidates[0].id, "fuzzy_name"

    return None, "unmatched"


def build_payments(statement, carrier, agent_id, agency_id, ws):
    """
    Parse the worksheet, build PolicyPayment rows, persist them.
    Deletes existing payments for this statement before inserting fresh ones
    so re-uploads are idempotent.
    """
    extractor = EXTRACTORS.get(carrier)
    if not extractor:
        return 0

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    items = extractor(rows)

    if not items:
        return 0

    # Build lookup indexes once
    all_policies = (Policy.query
                    .filter_by(agency_id=agency_id, status="active")
                    .with_entities(Policy.id, Policy.full_name, Policy.mbi,
                                   Policy.member_id, Policy.carrier)
                    .all())

    mbi_map        = {p.mbi: p.id for p in all_policies if p.mbi}
    carrier_id_map = {(p.carrier, p.member_id): p.id
                      for p in all_policies if p.member_id}

    # Agent name→id cache for multi-agent files (e.g. Aetna).
    # Resolves "Last, First" or "LAST, FIRST" to a portal user id.
    # Falls back to the statement-level agent_id (None for agency-level) if unmatched.
    from app.models import User as _User
    _all_users = _User.query.all()
    _agent_name_cache = {}
    def _resolve_agent_id(raw_name):
        if not raw_name:
            return agent_id
        if raw_name in _agent_name_cache:
            return _agent_name_cache[raw_name]
        norm = _norm(raw_name)
        matched = None
        # Exact match after normalisation
        for u in _all_users:
            if _norm(u.name) == norm:
                matched = u.id
                break
        if matched is None:
            # Fuzzy: match on last name + first 3 chars of first name
            # handles "Christopher Foster" → "Chris Foster"
            np = norm.split()
            for u in _all_users:
                up = _norm(u.name).split()
                if len(np) >= 2 and len(up) >= 2 and np[-1] == up[-1]:
                    if np[0][:3] == up[0][:3]:
                        matched = u.id
                        break
        _agent_name_cache[raw_name] = matched
        return matched if matched is not None else agent_id

    name_map       = {}
    for p in all_policies:
        norm = _norm(p.full_name)
        if norm:
            name_map.setdefault(norm, []).append(p)

    # Delete existing payments for this statement (idempotent re-upload)
    PolicyPayment.query.filter_by(statement_id=statement.id).delete()

    count = 0
    seen  = set()  # deduplicate within same upload (statement_id + norm_name + action)

    for item in items:
        norm_name = _norm(item["member_name"])
        action    = item["commission_action"]
        dedup_key = (norm_name, action)

        # For duplicate (name, action) pairs — e.g. BCBS with multiple coverage periods —
        # sum amounts rather than creating multiple rows
        if dedup_key in seen:
            # Find the existing payment and add to its amount
            existing = next(
                (p for p in db.session.new
                 if isinstance(p, PolicyPayment)
                 and p.statement_id == statement.id
                 and p.member_name_normalized == norm_name
                 and p.commission_action == action),
                None
            )
            if existing:
                existing.paid_amount += item["paid_amount"]
            continue

        seen.add(dedup_key)

        policy_id, confidence = _match_policy(
            item, carrier, agency_id, mbi_map, carrier_id_map, name_map
        )

        payment = PolicyPayment(
            agency_id              = agency_id,
            agent_id               = _resolve_agent_id(item.get("writing_agent_name")),
            statement_id           = statement.id,
            carrier                = carrier,
            period_label           = statement.period_label,
            statement_date         = statement.statement_date,
            member_name            = item["member_name"],
            member_name_normalized = norm_name,
            mbi                    = item.get("mbi"),
            carrier_member_id      = item.get("carrier_member_id"),
            policy_id              = policy_id,
            match_confidence       = confidence,
            commission_action      = action,
            paid_amount            = item["paid_amount"],
            is_chargeback          = item["paid_amount"] < 0 or action == "chargeback",
            effective_date         = item.get("effective_date"),
            term_date              = item.get("term_date"),
            term_reason            = item.get("term_reason"),
            period_month           = item.get("period_month"),
            plan_name              = item.get("plan_name"),
        )
        db.session.add(payment)
        count += 1

    db.session.flush()
    return count
