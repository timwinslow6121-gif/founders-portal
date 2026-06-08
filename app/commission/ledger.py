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
