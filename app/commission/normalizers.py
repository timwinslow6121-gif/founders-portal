"""
app/commission/normalizers.py

Per-carrier normalizers: raw sheets ({name: list[list[cell]]}) -> list[MemberFact].
Each carrier's native row-type vocabulary maps onto the common RowClass taxonomy.
Paired rows (Healthspring Service Fee + Broker Level; Devoted Override + Agent
Portion) are collapsed to ONE MemberFact per member.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §1 and
"Per-carrier reference".

Healthspring Detail column layout (0-indexed, verified against fixture):
  0  Payment Type        1  Payment Description (Service Fee | Broker Level)
  3  Writing Broker Name 5  Earner Name        7  Payment Amount
  8  Member ID           9  Medicare Beneficiary Identifier (MBI)
  10 Member Name         12 Effective Date      13 Member Term Date
  17 Plan Type           18 Plan Name           20 CMS Contract   21 PBP
"""
from app.commission.member_fact import MemberFact, RowClass
from app.commission.payments import _norm, _parse_date


def _to_float(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _classify_healthspring(payment_type, amount):
    pt = str(payment_type or "").lower()
    if amount < 0 or "disenroll" in pt:
        return RowClass.CHARGEBACK
    if "renewal" in pt:
        return RowClass.RENEWAL
    if "initial" in pt:   # "Initial - New to CMS" / "Initial - NOT New to CMS"
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_healthspring(sheets):
    rows = sheets.get("Detail", [])
    if not rows:
        return []
    facts_by_member = {}     # member_id -> MemberFact (Broker Level row)
    agency_by_member = {}    # member_id -> agency share amount (Service Fee row)

    for idx, row in enumerate(rows[1:], start=1):   # skip header
        if not any(row):
            continue
        member_id = str(row[8] or "").strip()
        if not member_id:
            continue
        desc = str(row[1] or "")                     # Service Fee | Broker Level
        amount = _to_float(row[7])

        if "service fee" in desc.lower():
            agency_by_member[member_id] = amount
            continue

        name = str(row[10] or "").strip()
        fact = MemberFact(
            carrier="Healthspring",
            full_name=name,
            first_name=name.split()[0] if name else "",
            last_name=name.split()[-1] if name else "",
            mbi=str(row[9] or "").strip() or None,
            carrier_member_id=member_id,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
            plan_contract=str(row[20] or "").strip() or None,
            plan_pbp=str(row[21] or "").strip() or None,
            plan_type=str(row[17] or "").strip() or None,
            row_class=_classify_healthspring(row[0], amount),
            amount=amount,
            writing_agent_raw=str(row[3] or "").strip(),
            source_ref=f"healthspring::Detail::{idx}",
        )
        facts_by_member[member_id] = fact

    for mid, fact in facts_by_member.items():
        fact.agency_share_amount = agency_by_member.get(mid)
    return list(facts_by_member.values())
