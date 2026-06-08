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
