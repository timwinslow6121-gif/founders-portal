"""
app/commission/ledger.py

R1 — Commission ledger completeness. Per-carrier *extractors* that mirror EVERY
amount-bearing row of a commission file into CommissionLineItem rows (the "money
facts" layer). Unlike app/commission/normalizers.py, extractors do NOT collapse
paired rows — the Founders-override / Service-Fee row is kept so that
"Σ raw_amount = Σ agent_payout + Σ founders_keep" is provable.

split_breakdown() is the single derivation seam: agent_payout / founders_keep
are always derived from raw_amount + split_rate + classification, never stored.

See docs/superpowers/specs/2026-06-08-commission-ledger-completeness-design.md.
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Tuple

# Classification constants (plain strings; no DB enum, forward-compat).
AGENT_COMMISSION = "agent_commission"
FOUNDERS_OVERRIDE = "founders_override"
HRA_BONUS = "hra_bonus"
CHARGEBACK = "chargeback"


@dataclass
class LineItemDraft:
    """In-memory line item before it is persisted as a CommissionLineItem.
    One per amount-bearing sheet row (paired rows NOT collapsed)."""
    carrier: str
    source_ref: str
    raw_amount: float
    classification: str
    split_rate: Optional[float] = None
    payment_type: Optional[str] = None
    member_name: str = ""
    mbi: Optional[str] = None
    carrier_member_id: Optional[str] = None
    writing_agent_raw: str = ""
    effective_date: Optional[date] = None
    term_date: Optional[date] = None


def split_breakdown(line) -> Tuple[float, float]:
    """Derive (agent_payout, founders_keep) from a line item / draft.

    - founders_override: agent gets nothing; Founders keeps the whole amount.
    - everything else (agent_commission / hra_bonus / chargeback): the amount is
      pre-split; agent_payout = raw_amount * split_rate, Founders keeps the rest.
      A None split_rate (no contract) yields payout 0 / keep = raw_amount.
    The two ALWAYS sum back to raw_amount (balance holds by construction)."""
    raw = line.raw_amount or 0.0
    if line.classification == FOUNDERS_OVERRIDE:
        return 0.0, raw
    rate = line.split_rate
    if rate is None:
        return 0.0, raw
    payout = raw * rate
    return payout, raw - payout


from app.commission.payments import _parse_date
from app.extensions import db
from app.models import CommissionLineItem


def _to_float(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _hs_classify(desc, amount):
    d = str(desc or "").lower()
    if "service fee" in d:
        return FOUNDERS_OVERRIDE
    if amount < 0:
        return CHARGEBACK
    return AGENT_COMMISSION


def extract_lineitems_healthspring(sheets, split_lookup) -> List[LineItemDraft]:
    """One LineItemDraft per Detail row (paired rows NOT collapsed).
    split_lookup(writing_agent_raw) -> Optional[float] split rate for that agent."""
    rows = sheets.get("Detail", [])
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        amount = _to_float(row[7])
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        classification = _hs_classify(desc, amount)
        writing = str(row[3] or "").strip()
        out.append(LineItemDraft(
            carrier="Healthspring",
            source_ref=f"healthspring::Detail::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=None if classification == FOUNDERS_OVERRIDE else split_lookup(writing),
            payment_type=str(row[0] or "").strip().lower() or None,
            member_name=str(row[10] or "").strip(),
            mbi=str(row[9] or "").strip() or None,
            carrier_member_id=member_id or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_healthspring(sheets) -> float:
    """Independent re-sum of EVERY Detail-row Payment Amount (col 7). Compared
    against the line-item sum to catch a dropped/mis-summed row."""
    rows = sheets.get("Detail", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 21:
            continue
        member_id = str(row[8] or "").strip()
        desc = str(row[1] or "")
        if not member_id and "service fee" not in desc.lower():
            continue
        total += _to_float(row[7])
    return total


def extract_lineitems_bcbs(sheets, split_lookup) -> List[LineItemDraft]:
    rows = sheets.get("Sheet1", [])
    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row) or len(row) <= 14:
            continue
        name = str(row[4] or "").strip()
        customer_no = str(row[5] or "").strip()
        if not name or not customer_no:        # skips Total: row
            continue
        amount = _to_float(row[14])            # Commission column, NOT Billed
        gt = str(row[2] or "").upper().strip()
        classification = CHARGEBACK if (amount < 0 or gt == "ADJUSTMENT") else AGENT_COMMISSION
        writing = str(row[1] or "").strip()
        out.append(LineItemDraft(
            carrier="BCBS",
            source_ref=f"bcbs::Sheet1::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=gt.lower() or None,
            member_name=name,
            mbi=None,
            carrier_member_id=customer_no,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[6]),
            term_date=_parse_date(row[9]),
        ))
    return out


def money_rows_total_bcbs(sheets) -> float:
    rows = sheets.get("Sheet1", [])
    total = 0.0
    for row in rows[1:]:
        if not any(row) or len(row) <= 14:
            continue
        if not str(row[4] or "").strip() or not str(row[5] or "").strip():
            continue
        total += _to_float(row[14])
    return total


def extract_lineitems_aetna(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    first = next(iter(sheets.values()))
    out = []
    for idx, row in enumerate(first[1:], start=1):
        if not any(row) or len(row) < 21:
            continue
        name = str(row[4] or "").strip()
        if not name:
            continue
        amount = _to_float(row[20])
        classification = CHARGEBACK if amount < 0 else AGENT_COMMISSION
        writing = str(row[16] or "").strip()
        out.append(LineItemDraft(
            carrier="Aetna",
            source_ref=f"aetna::0::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[6] or "").strip().lower() or None,
            member_name=name,
            mbi=str(row[1] or "").strip() or None,
            carrier_member_id=str(row[2] or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[12]),
            term_date=_parse_date(row[13]),
        ))
    return out


def money_rows_total_aetna(sheets) -> float:
    if not sheets:
        return 0.0
    first = next(iter(sheets.values()))
    total = 0.0
    for row in first[1:]:
        if not any(row) or len(row) < 21:
            continue
        if not str(row[4] or "").strip():
            continue
        total += _to_float(row[20])
    return total


def _devoted_sheet_rows(sheets, sheet_name):
    return sheets.get(sheet_name, [])


def _devoted_format(sheets):
    """Devoted ships two file shapes. Detect which by sheet names:
      - "agency"    : the agency book-of-business (Total/Override/Agent Portion/HRA)
      - "statement" : a per-agent statement (Summary/Detail/Misc)
    Raises ValueError on an unrecognized shape (fail loud, never silently 0 rows)."""
    if "Agent Portion" in sheets:
        return "agency"
    if "Detail" in sheets and "Misc" in sheets:
        return "statement"
    raise ValueError(
        f"Unrecognized Devoted file shape; sheets={list(sheets)}. "
        "Expected agency (Agent Portion) or statement (Detail+Misc).")


def extract_lineitems_devoted(sheets, split_lookup) -> List[LineItemDraft]:
    out = []
    # Agent Portion → agent_commission / chargeback
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Agent Portion")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        amount = _to_float(row[17])
        disen = _parse_date(row[10])
        classification = CHARGEBACK if (amount < 0 or disen) else AGENT_COMMISSION
        writing = str(row[2] or "").strip()
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::Agent Portion::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=str(row[15] or "").strip().lower() or None,
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=writing,
            effective_date=_parse_date(row[9]),
            term_date=disen,
        ))
    # Override → founders_override (no split)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "Override")[1:], start=1):
        if not any(row) or len(row) <= 17:
            continue
        member_id = str(row[3] or "").strip()
        if not member_id:
            continue
        first = str(row[5] or "").strip()
        last = str(row[6] or "").strip()
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::Override::{idx}",
            raw_amount=_to_float(row[17]),
            classification=FOUNDERS_OVERRIDE,
            split_rate=None,
            payment_type="override",
            member_name=f"{first} {last}".strip(),
            mbi=str(row[4] or "").strip() or None,
            carrier_member_id=member_id,
            writing_agent_raw=str(row[2] or "").strip(),
        ))
    # HRA → hra_bonus (split applies)
    for idx, row in enumerate(_devoted_sheet_rows(sheets, "HRA")[1:], start=1):
        if not any(row) or len(row) <= 3:
            continue
        rep = str(row[0] or "").strip()
        amt = _to_float(row[2])
        if not rep or amt == 0:
            continue
        out.append(LineItemDraft(
            carrier="Devoted",
            source_ref=f"devoted::HRA::{idx}",
            raw_amount=amt,
            classification=HRA_BONUS,
            split_rate=split_lookup(rep),
            payment_type="hra",
            member_name=str(row[3] or "").strip() or "HRA Bonus",
            writing_agent_raw=rep,
        ))
    return out


def money_rows_total_devoted(sheets) -> float:
    total = 0.0
    for row in _devoted_sheet_rows(sheets, "Agent Portion")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "Override")[1:]:
        if not any(row) or len(row) <= 17 or not str(row[3] or "").strip():
            continue
        total += _to_float(row[17])
    for row in _devoted_sheet_rows(sheets, "HRA")[1:]:
        if not any(row) or len(row) <= 3:
            continue
        if not str(row[0] or "").strip() or _to_float(row[2]) == 0:
            continue
        total += _to_float(row[2])
    return total


def _humana_cols(rows):
    header = rows[0]
    return {h: i for i, h in enumerate(header)}


def extract_lineitems_humana(sheets, split_lookup) -> List[LineItemDraft]:
    if not sheets:
        return []
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return []
    col = _humana_cols(rows)

    def g(row, key):
        i = col.get(key)
        return row[i] if i is not None and i < len(row) else ""

    out = []
    for idx, row in enumerate(rows[1:], start=1):
        if not any(row):
            continue
        umid = str(g(row, "UMID") or "").strip()
        grp = str(g(row, "GrpName") or "").strip()
        if not umid and not grp:
            continue
        amount = _to_float(g(row, "PaidAmount"))
        txn = str(g(row, "TxnTypeCd") or "").upper().strip()
        if txn == "HRAP":
            classification = HRA_BONUS
        elif amount < 0:
            classification = CHARGEBACK
        else:
            classification = AGENT_COMMISSION
        writing = str(g(row, "WaName") or "").strip()
        out.append(LineItemDraft(
            carrier="Humana",
            source_ref=f"humana::{name}::{idx}",
            raw_amount=amount,
            classification=classification,
            split_rate=split_lookup(writing),
            payment_type=txn.lower() or None,
            member_name=grp,
            mbi=umid or None,
            carrier_member_id=str(g(row, "PID") or "").strip() or None,
            writing_agent_raw=writing,
            effective_date=_parse_date(g(row, "EffDate")),
        ))
    return out


def money_rows_total_humana(sheets) -> float:
    if not sheets:
        return 0.0
    name = next((n for n in sheets if "CommissionData" in n), None) or next(iter(sheets))
    rows = sheets.get(name, [])
    if not rows:
        return 0.0
    col = _humana_cols(rows)
    pi = col.get("PaidAmount")
    ui = col.get("UMID")
    gi = col.get("GrpName")
    total = 0.0
    for row in rows[1:]:
        if not any(row):
            continue
        umid = str(row[ui] or "").strip() if ui is not None and ui < len(row) else ""
        grp = str(row[gi] or "").strip() if gi is not None and gi < len(row) else ""
        if not umid and not grp:
            continue
        if pi is not None and pi < len(row):
            total += _to_float(row[pi])
    return total


# (extractor, money_rows_total) per carrier. UHC deliberately absent (R4).
EXTRACTORS = {
    "Healthspring": (extract_lineitems_healthspring, money_rows_total_healthspring),
    "Devoted": (extract_lineitems_devoted, money_rows_total_devoted),
    "BCBS": (extract_lineitems_bcbs, money_rows_total_bcbs),
    "Aetna": (extract_lineitems_aetna, money_rows_total_aetna),
    "Humana": (extract_lineitems_humana, money_rows_total_humana),
}


@dataclass
class BalanceReport:
    carrier: str
    lineitem_total: float
    money_rows_total: float
    agent_payout_total: float
    founders_keep_total: float
    internal_ok: bool
    completeness_ok: bool

    def __str__(self):
        return (f"<BalanceReport {self.carrier} li={self.lineitem_total} "
                f"sheet={self.money_rows_total} payout={self.agent_payout_total} "
                f"keep={self.founders_keep_total} internal_ok={self.internal_ok} "
                f"completeness_ok={self.completeness_ok}>")


def verify_statement_balance(carrier, line_items, sheets, tol=0.01) -> BalanceReport:
    """Assert (1) internal balance: Σ raw == Σ payout + Σ keep (true by
    construction), and (2) completeness: Σ line-item raw == independent re-sum of
    the carrier's money rows from the raw sheets. A row the extractor dropped or
    mis-summed makes the two diverge → completeness_ok=False, naming the carrier.
    line_items may be LineItemDraft or persisted CommissionLineItem (both expose
    raw_amount / split_rate / classification)."""
    _, money_total_fn = EXTRACTORS[carrier]
    li_total = round(sum((li.raw_amount or 0.0) for li in line_items), 2)
    payout_total = 0.0
    keep_total = 0.0
    for li in line_items:
        p, k = split_breakdown(li)
        payout_total += p
        keep_total += k
    payout_total = round(payout_total, 2)
    keep_total = round(keep_total, 2)
    money_total = round(money_total_fn(sheets), 2)
    internal_ok = abs(li_total - (payout_total + keep_total)) <= tol
    completeness_ok = abs(li_total - money_total) <= tol
    return BalanceReport(
        carrier=carrier, lineitem_total=li_total, money_rows_total=money_total,
        agent_payout_total=payout_total, founders_keep_total=keep_total,
        internal_ok=internal_ok, completeness_ok=completeness_ok)


def persist_line_items(carrier, drafts, statement, agency_id, agent_resolver=None) -> int:
    """Insert/update CommissionLineItem rows for a statement, idempotent on
    (statement_id, source_ref). agent_resolver(writing_agent_raw) -> user_id|None
    resolves each draft's writing agent. Returns count written."""
    count = 0
    for d in drafts:
        agent_id = None
        if agent_resolver is not None and d.writing_agent_raw:
            agent_id = agent_resolver(d.writing_agent_raw)
        existing = (CommissionLineItem.query
                    .filter_by(statement_id=statement.id, agency_id=agency_id,
                               source_ref=d.source_ref)
                    .first())
        if existing is None:
            existing = CommissionLineItem(
                agency_id=agency_id, statement_id=statement.id,
                source_ref=d.source_ref, carrier=carrier)
            db.session.add(existing)
        existing.carrier = carrier
        existing.period_label = statement.period_label
        existing.statement_date = statement.statement_date
        existing.agent_id = agent_id
        existing.member_name = d.member_name
        existing.mbi = d.mbi
        existing.carrier_member_id = d.carrier_member_id
        existing.raw_amount = d.raw_amount
        existing.split_rate = d.split_rate
        existing.classification = d.classification
        existing.payment_type = d.payment_type
        count += 1
    return count
