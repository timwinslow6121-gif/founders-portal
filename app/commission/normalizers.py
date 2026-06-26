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
from app.commission.payments import _parse_date
from app.commission.ledger import _devoted_format, _devoted_filetoken
from app.names import normalize_person_name


def _to_float(v):
    s = str(v).replace("$", "").replace(",", "").strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):   # accounting-style negative
        s = s[1:-1].strip()
        neg = True
    try:
        n = float(s or 0)
    except (ValueError, TypeError):
        return 0.0
    return -n if neg else n


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
    from app.commission.ledger import _healthspring_filetoken
    rows = sheets.get("Detail", [])
    if not rows:
        return []
    filetoken = _healthspring_filetoken(sheets)
    facts_by_member = {}     # member_id -> MemberFact (Broker Level row)
    agency_by_member = {}    # member_id -> agency share amount (Service Fee row)

    for idx, row in enumerate(rows[1:], start=1):   # skip header
        if not any(row):
            continue
        if len(row) <= 21:
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
        first_n, mi, last_n, full = normalize_person_name(name)
        fact = MemberFact(
            carrier="Healthspring",
            full_name=full,
            first_name=first_n,
            last_name=last_n,
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
            source_ref=f"healthspring::{filetoken}::Detail::{idx}",
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
    fmt = _devoted_format(sheets)
    filetoken = _devoted_filetoken(sheets)
    if fmt == "statement":
        return _normalize_devoted_statement(sheets, filetoken)
    return _normalize_devoted_agency(sheets, filetoken)


def _normalize_devoted_agency(sheets, filetoken):
    facts = {}        # member_id -> MemberFact (from Agent Portion)
    agency = {}       # member_id -> Override admin amount

    for idx, row in enumerate(sheets.get("Agent Portion", [])[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        first_n, mi, last_n, full = normalize_person_name(f"{last}, {first}")
        disen = _parse_date(row[10])
        facts[member_id] = MemberFact(
            carrier="Devoted",
            full_name=full,
            first_name=first_n,
            last_name=last_n,
            mbi=str(row[4] or "").strip() or None,    # HICN (MBI-shaped)
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::{filetoken}::Agent Portion::{idx}",
        )

    for idx, row in enumerate(sheets.get("Override", [])[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 17:
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
        if len(row) <= 3:
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
            source_ref=f"devoted::{filetoken}::HRA::{idx}",
        ))
    return out


def _normalize_devoted_statement(sheets, filetoken):
    """Rebekah per-agent statement → MemberFacts. Detail rows are member
    commissions; Misc rows are HRA (NON_CUSTOMER, often negative clawbacks).
    Summary is ignored (prior-period carryforward)."""
    out = []
    for idx, row in enumerate(sheets.get("Detail", [])[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        first_n, mi, last_n, full = normalize_person_name(f"{last}, {first}")
        disen = _parse_date(row[10])
        out.append(MemberFact(
            carrier="Devoted",
            full_name=full,
            first_name=first_n,
            last_name=last_n,
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            effective_date=_parse_date(row[9]),
            term_date=disen,
            plan_contract=str(row[11] or "").strip() or None,
            plan_pbp=str(row[12] or "").strip() or None,
            row_class=_classify_devoted(row[15], amount, disen),
            amount=amount,
            writing_agent_raw=str(row[2] or "").strip(),
            source_ref=f"devoted::{filetoken}::Detail::{idx}",
        ))
    for idx, row in enumerate(sheets.get("Misc", [])[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(MemberFact(
            carrier="Devoted",
            full_name=str(row[3] or "").strip() or "HRA",
            row_class=RowClass.NON_CUSTOMER,
            amount=amt,
            writing_agent_raw=rep,
            source_ref=f"devoted::{filetoken}::Misc::{idx}",
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
    from app.commission.ledger import _bcbs_filetoken
    rows = sheets.get("Sheet1", [])
    if not rows:
        return []
    filetoken = _bcbs_filetoken(sheets)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        if len(row) <= 14:
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row
            continue
        first_n, mi, last_n, full = normalize_person_name(name)
        amount = _to_float(row[14])
        out.append(MemberFact(
            carrier="BCBS",
            full_name=full,
            first_name=first_n,
            last_name=last_n,
            mbi=None,
            carrier_member_id=customer_no,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
            plan_type=str(row[7] or "").strip() or None,
            row_class=_classify_bcbs(row[2], amount),
            amount=amount,
            writing_agent_raw=str(row[1] or "").strip(),
            source_ref=f"bcbs::{filetoken}::Sheet1::{idx}",
        ))
    return out


# ---------------------------------------------------------------------------
# Aetna
#
# Agency-level multi-agent file (one sheet, named after agency, e.g.
# "Founders Insurance Agency, LLC_"). Column layout (0-indexed, verified
# against fixture):
#   0  Payment Date      1  Medicare Number (MBI)     2  Member ID
#   4  Member Name       6  Sales Event               7  Product (MAPD/PDP)
#   9  Plan ID           12 Effective Date            13 Term Date
#   16 Writing Agent Name 20 Payee Amount
#
# Sales Event taxonomy:
#   "Renewal"            -> RENEWAL
#   "Pro-Rata Payment"   -> ENROLLMENT (new sale)
#   "Pro-Rata Disenroll" or amount < 0 -> CHARGEBACK
# Plan ID like "H3146-006" splits into contract="H3146", pbp="006".
# ---------------------------------------------------------------------------
def _split_plan_id(plan_id):
    """'H3146-006' -> ('H3146', '006'); 'S5601-016' -> ('S5601','016')."""
    s = str(plan_id or "").strip()
    if "-" in s:
        a, b = s.split("-", 1)
        return a.strip() or None, b.strip() or None
    return (s or None), None


def _classify_aetna(sales_event, amount):
    se = str(sales_event or "").lower()
    if amount < 0 or "disenroll" in se:
        return RowClass.CHARGEBACK
    if "renewal" in se:
        return RowClass.RENEWAL
    if "pro-rata" in se or "new" in se:
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_aetna(sheets):
    """Agency-level Aetna file: one sheet, named after the agency."""
    if not sheets:
        return []
    first = next(iter(sheets.values()))
    if not first:
        return []
    out = []
    for idx, row in enumerate(first[1:], start=1):
        if not any(row) or len(row) < 21:
            continue
        name = str(row[4] or "").strip()
        if not name:
            continue
        first, mi, last, full = normalize_person_name(name)
        amount = _to_float(row[20])
        contract, pbp = _split_plan_id(row[9])
        out.append(MemberFact(
            carrier="Aetna",
            full_name=full,
            first_name=first,
            last_name=last,
            mbi=str(row[1] or "").strip() or None,
            carrier_member_id=str(row[2] or "").strip() or None,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
            plan_contract=contract,
            plan_pbp=pbp,
            plan_type=str(row[7] or "").strip() or None,
            row_class=_classify_aetna(row[6], amount),
            amount=amount,
            writing_agent_raw=str(row[16] or "").strip(),
            source_ref=f"aetna::0::{idx}",
        ))
    return out


def _classify_humana(txn_type, amount):
    t = str(txn_type or "").upper().strip()
    if amount < 0:
        return RowClass.CHARGEBACK
    if t == "ARCM":          # renewal commissions
        return RowClass.RENEWAL
    if t in ("ARCF", "MED2", "ICCF", "ICFA"):   # first-year / 2nd-half first-year
        return RowClass.ENROLLMENT
    if t in ("HRAP",):       # HRA bonus
        return RowClass.NON_CUSTOMER
    return RowClass.RENEWAL


def _humana_name(grp_name):
    """'VILLEGAS ANASTACIO Z' -> (full as-is, first(guess), last(guess))."""
    s = str(grp_name or "").strip()
    parts = s.split()
    if len(parts) >= 2:
        return s, parts[1], parts[0]
    return s, "", s


# ── UHC (raw 'Commission Transactions' sheet) ─────────────────────────────
# Customer-sync normalizer for the raw UHC statement. Reduces each member row to
# ONE MemberFact (the ledger extractor in ledger.py handles the override SPLIT
# separately — different purpose). Column indices reuse the ledger's constants.
from app.commission.ledger import (
    _UHC_SHEET, _UHC_AGENT, _UHC_MEMBER, _UHC_MBI, _UHC_PLANTYPE,
    _UHC_ACTION, _UHC_AMOUNT, _UHC_EFFDATE, _UHC_OVERRIDE, _near,
    _UHC_WRITING_ID, _uhc_writing_id_map,
)

_UHC_CONTRACT = 13
_UHC_PBP = 14


def _classify_uhc(action, amount, plan_type, member="", mbi=None):
    """Map a UHC row to the 4-value RowClass taxonomy for customer sync.

    HA bonuses, pure Founders-override rows ($4.59), and sub-$1 PARTD "dust" are
    real payments but NOT a member enrollment/renewal — NON_CUSTOMER so they
    write a payment without spawning a junk stub customer. (The ledger extractor
    separately decides their split.)"""
    a = str(action or "").lower()
    plan = str(plan_type or "").upper().strip()

    # No usable member identity (e.g. DVH Manual Payment — the member name is
    # buried in the action string, not the member column). Can't be a real
    # customer; treat as a payment only, no junk stub.
    if not str(member or "").strip() and not (mbi or "").strip():
        return RowClass.NON_CUSTOMER
    if a.startswith("ha payment") or a.startswith("ha chargeback"):
        return RowClass.NON_CUSTOMER
    # pure override-only row (the flat $4.59, either sign)
    if _near(abs(amount), _UHC_OVERRIDE):
        return RowClass.NON_CUSTOMER
    # PARTD dust AJ drops (sub-$1, not the override)
    if plan == "PARTD" and abs(amount) < 1.00:
        return RowClass.NON_CUSTOMER

    if amount < 0 or "chargeback" in a:
        return RowClass.CHARGEBACK
    if a.startswith("new"):
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_uhc(sheets, writing_id_to_name=None, agency_id=None):
    """Agency-level raw UHC file: data on the 'Commission Transactions' sheet.

    Attribute the writing agent by Writing Agent ID (col 4), NOT the name (col 5) —
    Rebekah & others write their whole book under 'FOUNDERS INSURANCE AGENCY, LLC',
    so name attribution leaves them unassigned. Mirrors the ledger extractor so the
    customer-sync pass and the ledger agree on the agent."""
    rows = sheets.get(_UHC_SHEET) if sheets else None
    if not rows:
        return []
    if writing_id_to_name is None:
        try:
            writing_id_to_name = _uhc_writing_id_map(agency_id)
        except RuntimeError:
            writing_id_to_name = {}
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= _UHC_AMOUNT:
            continue
        amount = round(_to_float(row[_UHC_AMOUNT]), 2)
        if amount == 0:
            continue
        member = str(row[_UHC_MEMBER] or "").strip()
        wid = str(row[_UHC_WRITING_ID] or "").strip() if len(row) > _UHC_WRITING_ID else ""
        agent = writing_id_to_name.get(wid) or str(row[_UHC_AGENT] or "").strip()
        plan_type = str(row[_UHC_PLANTYPE] or "").strip() or None
        action = str(row[_UHC_ACTION] or "").strip()
        first, mi, last, full = normalize_person_name(member)
        out.append(MemberFact(
            carrier="UHC",
            full_name=full,
            first_name=first,
            last_name=last,
            mbi=str(row[_UHC_MBI] or "").strip() or None,
            effective_date=_parse_date(row[_UHC_EFFDATE]) if len(row) > _UHC_EFFDATE else None,
            plan_contract=str(row[_UHC_CONTRACT] or "").strip() or None,
            plan_pbp=str(row[_UHC_PBP] or "").strip() or None,
            plan_type=plan_type,
            row_class=_classify_uhc(action, amount, plan_type, member,
                                    str(row[_UHC_MBI] or "").strip()),
            amount=amount,
            writing_agent_raw=agent,
            source_ref=f"uhc::0::{idx}",
        ))
    return out


def normalize_humana(sheets):
    if not sheets:
        return []
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return []
    header = rows[0]
    col = {h: i for i, h in enumerate(header)}

    def g(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        umid = str(g(row, "UMID") or "").strip()
        grp = g(row, "GrpName")
        if not umid and not grp:
            continue
        amount = _to_float(g(row, "PaidAmount"))
        _, guess_first, guess_last = _humana_name(grp)
        first, mi, last, full = normalize_person_name(f"{guess_last}, {guess_first}")
        out.append(MemberFact(
            carrier="Humana",
            full_name=full,
            first_name=first,
            last_name=last,
            mbi=umid or None,
            carrier_member_id=str(g(row, "PID") or "").strip() or None,
            effective_date=_parse_date(g(row, "EffDate")),
            plan_contract=str(g(row, "Contract") or "").strip() or None,
            row_class=_classify_humana(g(row, "TxnTypeCd"), amount),
            amount=amount,
            writing_agent_raw=str(g(row, "WaName") or "").strip(),
            source_ref=f"humana::{name}::{idx}",
        ))
    return out


# ── Carrier dispatch registry ──────────────────────────────────────────────────
# UHC is intentionally absent — its lumped LOA split needs the provenance-style
# inferred-split + AJ override, built last (Plan 6).
NORMALIZERS = {
    "Healthspring": normalize_healthspring,
    "Devoted": normalize_devoted,
    "BCBS": normalize_bcbs,
    "Aetna": normalize_aetna,
    "Humana": normalize_humana,
    "UHC": normalize_uhc,
}
