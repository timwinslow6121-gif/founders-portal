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
    # "Initial - New" AND "Initial - Not New" are both first-year enrollments —
    # 'Not New' means not new to Medicare, not "not a new enrollment". Match on
    # the 'initial' prefix: a bare `"new" in ct` also matched "Renewal - Monthly"
    # (re-NEW-al), classifying every renewal as an enrollment.
    if ct.startswith("initial"):
        return RowClass.ENROLLMENT
    if "renewal" in ct:
        return RowClass.RENEWAL
    if "new" in ct:
        return RowClass.ENROLLMENT
    return RowClass.RENEWAL


def normalize_devoted(sheets):
    fmt = _devoted_format(sheets)
    filetoken = _devoted_filetoken(sheets)
    if fmt == "statement":
        return _normalize_devoted_statement(sheets, filetoken)
    if fmt == "statement2026":
        return _normalize_devoted_statement_2026(sheets, filetoken)
    if fmt == "tmg":
        return _normalize_tidewater(sheets, filetoken)
    return _normalize_devoted_agency(sheets, filetoken)


def _hdr_index(rows):
    """{lowercased header name: column index} for a header-row sheet."""
    if not rows:
        return {}
    return {str(c or "").strip().lower(): i for i, c in enumerate(rows[0])}


def _normalize_devoted_statement_2026(sheets, filetoken):
    """Devoted's 2026-08 per-agent statement: Transactions / Statement Summary.

    Replaces the Summary/Detail shape. 'Member HICN' -> 'MBI', 'Agent NPN' ->
    'Agent ID', and a 'Contract' column (H9700) now carries the plan. Read BY
    HEADER NAME, not fixed index: the previous layout's indices are exactly what
    broke when Devoted re-cut the file.

    The Statement Summary sheet is NOT extracted -- its Statement Total already
    nets a 'Balance Adjustment' (a prior-period carryforward), so importing it
    would double-count. Verified: Transactions sum 2602.49, minus the -168.74
    adjustment, equals the summary's 2433.75.
    """
    rows = sheets.get("Transactions", [])
    ix = _hdr_index(rows)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue

        def g(name):
            i = ix.get(name)
            return str(row[i] or "").strip() if i is not None and i < len(row) else ""

        amount = _to_float(g("amount"))
        if amount == 0:
            continue
        member = g("member")
        first_n, mi, last_n, full = normalize_person_name(member)
        disen = None if g("disenroll/cancel").lower() in ("", "no") else _parse_date(g("effective date"))
        out.append(MemberFact(
            carrier="Devoted",
            full_name=full or member,
            first_name=first_n,
            last_name=last_n,
            mbi=g("mbi") or None,
            carrier_member_id=g("mbi") or None,
            effective_date=_parse_date(g("effective date")),
            term_date=disen,
            plan_contract=g("contract") or None,
            row_class=_classify_devoted(g("type"), amount, disen),
            amount=amount,
            writing_agent_raw=g("agent"),
            source_ref=f"devoted::{filetoken}::Transactions::{idx}",
        ))
    return out


def _normalize_tidewater(sheets, filetoken):
    """Tidewater Management Group (TMG) FMO statement -- one 'Agent Report' sheet.

    This is NOT a carrier export: TMG pays Founders for business written with a
    carrier named in its own 'Carrier' column (DEVOTEDHEALTH here). It is parsed
    under Devoted because that is the carrier in this file, and the column is
    read rather than assumed so a future TMG file for another carrier surfaces
    instead of being silently mislabelled.

    TWO TRAPS, both verified against the real 2026-08 file:

    1. SUMMARY ROWS. Two rows carry 'Total Amount:' / 'Payment Amount:' in the
       Member Count column and repeat the statement total -- $13,306.56, or 67%
       of the raw sum. Importing them would more than double the statement.
       Excluded by requiring a Payee ID, which the summary rows lack.

    2. AGENT vs FOUNDERS. 'Transaction Type' already splits Commission (the
       writing agent's share) from Override (Founders'). Treating every row as
       agent commission would double-count. Override rows are flagged
       is_agency_share so the split is not recomputed downstream.

    Verified: 53 data rows = $6,653.28, matching the file's own total to the
    penny; Commission $5,204.96 + Override $1,448.32; 12 chargebacks -$1,596.56.
    """
    rows = sheets.get("Agent Report", [])
    ix = _hdr_index(rows)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue

        def g(name):
            i = ix.get(name)
            return str(row[i] or "").strip() if i is not None and i < len(row) else ""

        # Summary rows ('Total Amount:' / 'Payment Amount:') carry no Payee ID.
        if not g("payee id"):
            continue
        amount = _to_float(g("amount"))
        if amount == 0:
            continue

        carrier_raw = g("carrier").upper()
        carrier = "Devoted" if "DEVOTED" in carrier_raw else (carrier_raw.title() or "Devoted")

        insured = g("insured")
        first_n, mi, last_n, full = normalize_person_name(insured)
        is_override = g("transaction type").lower() == "override"
        ctype = g("carrier transaction type")

        if amount < 0:
            row_class = RowClass.CHARGEBACK
        elif ctype.lower().startswith("initial"):
            row_class = RowClass.ENROLLMENT
        else:
            row_class = RowClass.RENEWAL

        out.append(MemberFact(
            carrier=carrier,
            full_name=full or insured,
            first_name=first_n,
            last_name=last_n,
            carrier_member_id=g("policy") or None,
            effective_date=_parse_date(g("effective date")),
            plan_contract=None,
            row_class=row_class,
            amount=amount,
            is_agency_share=is_override,
            writing_agent_raw=g("writing agent name"),
            source_ref=f"devoted::{filetoken}::Agent Report::{idx}",
        ))
    return out


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


class BcbsColumnError(ValueError):
    """A required BCBS column could not be found in the file's header row.

    BCBS commission data reaches us via Tidewater (Founders' upline FMO), whose
    export layout varies month to month (columns added / removed / reordered —
    e.g. May had a 'Customer Type' column June didn't). We therefore resolve
    columns by HEADER NAME, not fixed position, and raise this loud, specific
    error naming the missing field + the headers we DID see — so a future format
    change is diagnosable rather than a silent 'no rows found'.
    """


# Header aliases per logical BCBS field. Matched case-insensitively with
# whitespace stripped. Add a new alias here when Tidewater renames a column.
_BCBS_COLUMN_ALIASES = {
    "name":        ("customer name", "customer", "member name"),
    "customer_no": ("customer no", "customer #", "customer number", "cust no", "customer no."),
    "commission":  ("commission", "commission amount", "comm amount", "comm amt"),
    # NOTE: no bare "type" alias — it drives the chargeback SIGN, and a stray
    # "Customer Type"/other *Type* column (exactly what caused the original bug)
    # must never be mistaken for "Group Type". Only match the specific header.
    "group_type":  ("group type",),
    "agent":       ("agent name", "agent"),
    "eff_date":    ("orig eff date", "origeffdate", "effective date", "eff date"),
    "term_date":   ("coverage to", "coverageto", "coverage end", "disenroll date"),
    "product":     ("product", "plan"),
}
# Fields the parser cannot work without; a missing one is a loud error.
_BCBS_REQUIRED = ("name", "customer_no", "commission")


def _resolve_bcbs_columns(header_row):
    """Map each logical BCBS field to its column index by header name (alias-aware).
    Raises BcbsColumnError naming any REQUIRED field that can't be found."""
    seen = [str(h or "").strip() for h in header_row]
    lookup = {h.lower(): i for i, h in enumerate(seen) if h}
    cols = {}
    for field, aliases in _BCBS_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                cols[field] = lookup[alias]
                break
    missing = [f for f in _BCBS_REQUIRED if f not in cols]
    if missing:
        raise BcbsColumnError(
            f"BCBS file: could not find required column(s) "
            f"{', '.join(repr(m) for m in missing)} — headers seen: {seen}. "
            f"The BCBS/Tidewater format may have changed; check the column names."
        )
    return cols


def normalize_bcbs(sheets):
    from app.commission.ledger import _bcbs_filetoken
    rows = sheets.get("Sheet1", [])
    if not rows:
        return []
    cols = _resolve_bcbs_columns(rows[0])   # raises BcbsColumnError if a required col is missing
    filetoken = _bcbs_filetoken(sheets)
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        name = str(row[cols["name"]] or "").strip() if cols["name"] < len(row) else ""
        customer_no = str(row[cols["customer_no"]] or "").strip() if cols["customer_no"] < len(row) else ""
        if not name or not customer_no:        # skips Total: row
            continue
        first_n, mi, last_n, full = normalize_person_name(name)
        amount = _to_float(row[cols["commission"]]) if cols["commission"] < len(row) else 0.0

        def _cell(field):
            ci = cols.get(field)
            return row[ci] if ci is not None and ci < len(row) else None

        out.append(MemberFact(
            carrier="BCBS",
            full_name=full,
            first_name=first_n,
            last_name=last_n,
            mbi=None,
            carrier_member_id=customer_no,
            effective_date=_parse_date(_cell("eff_date")),
            term_date=_parse_date(_cell("term_date")),
            plan_type=str(_cell("product") or "").strip() or None,
            row_class=_classify_bcbs(_cell("group_type"), amount),
            amount=amount,
            writing_agent_raw=str(_cell("agent") or "").strip(),
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
    rows = next(iter(sheets.values()))
    if not rows:
        return []
    out = []
    for idx, row in enumerate(rows[1:], start=1):
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


_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}


def _humana_name(grp_name):
    """Humana GrpName is 'LAST [SUFFIX] FIRST [MIDDLE]' (e.g. 'VILLEGAS ANASTACIO Z' or
    'MORGAN JR BILLY N'). Return (full as-is, first(guess), last(guess)). The first-name
    guess is the first NON-SUFFIX token after the last name — a suffix (JR/SR/III…) right
    after the last name must NOT be mistaken for the first name (that dropped the real
    first name and produced customers stored as 'Jr Morgan')."""
    s = str(grp_name or "").strip()
    parts = s.split()
    if len(parts) >= 2:
        last = parts[0]
        rest = [p for p in parts[1:] if p.upper().strip(".") not in _NAME_SUFFIXES]
        first = rest[0] if rest else ""
        return s, first, last
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
            member_group_key=str(g(row, "GrpNbr") or "").strip() or None,
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
