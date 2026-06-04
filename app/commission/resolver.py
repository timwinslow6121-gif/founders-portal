"""
app/commission/resolver.py

The ONE identity codepath for both commission upload and BOB upload. Turns a
MemberFact into a resolved (Customer, Policy) with lifecycle side effects
(carrier-switch terming, new AOR interval, rapid_disenroll flag) and, when it
cannot confidently match, a stub + a MatchSuggestion for human confirm.

Resolution order: crosswalk (Policy by carrier+member_id) → MBI → suggest-link →
stub. See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §2.
"""
from dataclasses import dataclass, field
from typing import Optional, List

from app.extensions import db
from app.models import Customer, Policy
from app.commission.member_fact import MemberFact, RowClass


@dataclass
class ResolveResult:
    customer: Optional[Customer] = None
    policy: Optional[Policy] = None
    created_customer: bool = False
    created_policy: bool = False
    match_path: str = ""           # crosswalk | mbi | suggest_link | stub
    actions: List[str] = field(default_factory=list)


def _crosswalk(fact: MemberFact, agency_id: int):
    """Return existing Policy matched by (carrier, carrier_member_id), else None."""
    cid = (fact.carrier_member_id or "").strip()
    if not cid:
        return None
    return (Policy.query
            .filter_by(agency_id=agency_id, carrier=fact.carrier, member_id=cid)
            .first())


def resolve_customer(fact: MemberFact, *, agency_id: int, agent_id: Optional[int],
                     batch_id: Optional[int] = None, source: str = "commission_import"
                     ) -> ResolveResult:
    result = ResolveResult()

    # 1. Crosswalk — deterministic monthly re-link
    policy = _crosswalk(fact, agency_id)
    if policy is not None:
        customer = Customer.query.get(policy.customer_id) if policy.customer_id else None
        if customer is not None:
            result.customer = customer
            result.policy = policy
            result.match_path = "crosswalk"
            return result

    # later steps (MBI, suggest-link, stub) added in subsequent tasks
    return result
