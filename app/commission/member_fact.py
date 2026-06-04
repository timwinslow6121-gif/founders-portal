"""
app/commission/member_fact.py

The carrier-agnostic contract between commission-file normalizers and the
customer-resolution service. Every carrier file is reduced to a list of
MemberFact; the resolver never sees a carrier's raw format.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §1.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


class RowClass:
    """Common taxonomy each carrier's native row-type vocabulary maps onto."""
    ENROLLMENT = "enrollment"      # new sale → create/confirm customer + open AOR
    RENEWAL = "renewal"            # confirm existing AOR, record payment
    CHARGEBACK = "chargeback"      # negative/clawback → payment+lifecycle, NO customer create
    NON_CUSTOMER = "non_customer"  # HRA bonus, summary line → payment only, NO customer


@dataclass
class MemberFact:
    # identity
    carrier: str
    full_name: str
    first_name: str = ""
    last_name: str = ""
    mbi: Optional[str] = None
    carrier_member_id: Optional[str] = None
    dob: Optional[date] = None

    # lifecycle
    effective_date: Optional[date] = None
    term_date: Optional[date] = None
    plan_contract: Optional[str] = None   # "H9725"
    plan_pbp: Optional[str] = None        # "015"
    plan_type: Optional[str] = None       # "MAPD" / "DSNP" ...

    # classification + money
    row_class: str = RowClass.RENEWAL
    amount: float = 0.0                   # may be negative (chargeback)
    is_agency_share: bool = False         # reserved for a later plan; collapse currently carries agency share via agency_share_amount

    # agent / split (populated by later plans; normalizer sets writing_agent_raw only)
    writing_agent_raw: str = ""
    resolved_agent_id: Optional[int] = None
    contract_active: Optional[bool] = None
    split_rate: Optional[float] = None
    agent_share: Optional[Decimal] = None
    split_flag: Optional[str] = None      # None | 'no_contract' | 'provenance_conditional'

    # audit / idempotency
    source_ref: str = ""                  # "file::sheet::rowindex"

    # carry the agency-share amount when paired rows are collapsed (Healthspring/Devoted)
    agency_share_amount: Optional[float] = None
