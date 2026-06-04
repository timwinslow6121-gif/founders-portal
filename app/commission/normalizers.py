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


# ---------------------------------------------------------------------------
# Devoted
#
# Agency file has 4 sheets: Total, Override, Agent Portion, HRA.
# The SAME member appears in both "Agent Portion" (agent share, "Base Amount")
# and "Override" (agency share, "Admin Amount"). Collapse to ONE MemberFact:
#   amount               = Agent Portion Base Amount
#   agency_share_amount  = Override Admin Amount
# HRA sheet = $50 bonuses -> NON_CUSTOMER facts with carrier_member_id=None.
# Negative Base Amount OR a Disenroll Date present = CHARGEBACK.
#
# Column layout (0-indexed, verified against fixture; identical for both
# Agent Portion and Override):
#   0  Statement Date  1  Agent NPN     2  Agent Name      3  Member ID
#   4  Member HICN     5  Member First  6  Member Last     7  Member State
#   8  Signature Date  9  Effective Date 10 Disenroll Date 11 Contract
#   12 PBP             13 Prior Plan Type 14 CMS Cycle Year 15 Commission Type
#   16 Period          17 Base Amount (Agent Portion) / Admin Amount (Override)
# HRA: 0 Rep Name  1 Rep ID  2 Amount  3 Note
# ---------------------------------------------------------------------------
def _classify_devoted(commission_type, amount, disenroll):
    if amount < 0 or disenroll:
        return RowClass.CHARGEBACK
    ct = str(commission_type or "").lower()
    if "new" in ct:        # "Initial - New" / "Initial - Not New"
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_devoted(sheets):
    facts = {}        # member_id -> MemberFact (from Agent Portion)
    agency = {}       # member_id -> Override admin amount

    for idx, row in enumerate(sheets.get("Agent Portion", [])[1:], start=1):
        if not any(row):
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        disen = _parse_date(row[10])
        facts[member_id] = MemberFact(
            carrier="Devoted",
            full_name=f"{first} {last}".strip(),
            first_name=first,
            last_name=last,
            mbi=str(row[4] or "").strip() or None,    # HICN (MBI-shaped)
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::Agent Portion::{idx}",
        )

    for idx, row in enumerate(sheets.get("Override", [])[1:], start=1):
        if not any(row):
            continue
        member_id = str(row[3] or "").strip()
        if member_id:
            agency[member_id] = _to_float(row[17])

    for mid, fact in facts.items():
        fact.agency_share_amount = agency.get(mid)

    out = list(facts.values())

    for idx, row in enumerate(sheets.get("HRA", [])[1:], start=1):
        if not any(row):
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(MemberFact(
            carrier="Devoted",
            full_name=str(row[3] or "").strip() or "HRA Bonus",
            row_class=RowClass.NON_CUSTOMER,
            amount=amt,
            writing_agent_raw=rep,
            source_ref=f"devoted::HRA::{idx}",
        ))
    return out


# ---------------------------------------------------------------------------
# BCBS
#
# Columns (0-indexed, verified against fixture):
#   0  Agent #           1  Agent Name        2  Group Type (FY | NEW | RENEW | ADJUSTMENT)
#   3  Customer Type     4  Customer Name     5  Customer No (stable id, no MBI)
#   6  Orig Eff Date     7  Product           8  Coverage From
#   9  Coverage To       10 Premium Period    11 Orig Sub Count
#   12 Renewal Date      13 Billed Amount     14 Commission
#
# Group Type = FY|NEW → ENROLLMENT, RENEW → RENEWAL, ADJUSTMENT|negative amount → CHARGEBACK
# Trailing "Total:" row is skipped (no Customer No).
# Customer Name is "Last,First M" format.
# No MBI column; carrier_member_id = Customer No.
# ---------------------------------------------------------------------------
def _classify_bcbs(group_type, amount):
    gt = str(group_type or "").upper().strip()
    if amount < 0 or gt == "ADJUSTMENT":
        return RowClass.CHARGEBACK
    if gt == "RENEW":
        return RowClass.RENEWAL
    if gt in ("FY", "NEW"):
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_bcbs(sheets):
    rows = sheets.get("Sheet1", [])
    if not rows:
        return []
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row
            continue
        if "," in name:
            last, first_rest = [p.strip() for p in name.split(",", 1)]
            first = first_rest.split()[0] if first_rest else ""
        else:
            last, first = name, ""
        amount = _to_float(row[14])
        out.append(MemberFact(
            carrier="BCBS",
            full_name=name,
            first_name=first,
            last_name=last,
            mbi=None,
            carrier_member_id=customer_no,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
            plan_type=str(row[7] or "").strip() or None,
            row_class=_classify_bcbs(row[2], amount),
            amount=amount,
            writing_agent_raw=str(row[1] or "").strip(),
            source_ref=f"bcbs::Sheet1::{idx}",
        ))
    return out
