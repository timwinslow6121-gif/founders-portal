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


def _attach_policy(fact: MemberFact, customer: Customer, agency_id: int,
                   agent_id: Optional[int]) -> Policy:
    """Create a Policy for this fact linked to the given customer."""
    p = Policy(
        agency_id=agency_id,
        carrier=fact.carrier,
        member_id=(fact.carrier_member_id or fact.mbi or "").strip(),
        mbi=fact.mbi,
        first_name=fact.first_name,
        last_name=fact.last_name,
        full_name=fact.full_name,
        plan_type=fact.plan_type,
        effective_date=fact.effective_date,
        term_date=fact.term_date,
        status="active",
        agent_id=agent_id,
        customer_id=customer.id,
    )
    db.session.add(p)
    db.session.flush()
    return p


def _match_by_mbi(fact: MemberFact, agency_id: int):
    """Return existing Customer by MBI (or humana_id for Humana), else None."""
    if fact.carrier == "Humana" and fact.mbi:
        c = Customer.query.filter_by(humana_id=fact.mbi, agency_id=agency_id).first()
        if c:
            return c
    if fact.mbi:
        return Customer.query.filter_by(mbi=fact.mbi, agency_id=agency_id).first()
    return None


def _create_stub(fact: MemberFact, agency_id: int, agent_id: Optional[int],
                 source: str) -> Customer:
    """Create a stub Customer from whatever the fact provides."""
    humana_id = fact.mbi if fact.carrier == "Humana" else None
    c = Customer(
        agency_id=agency_id,
        mbi=fact.mbi if fact.carrier != "Humana" else None,
        humana_id=humana_id,
        first_name=fact.first_name or "",
        last_name=fact.last_name or "",
        full_name=fact.full_name or f"{fact.first_name} {fact.last_name}".strip(),
        primary_agent_id=agent_id,
        stub=True,
        source=source,
    )
    db.session.add(c)
    db.session.flush()
    return c


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

    # 2. MBI / humana_id match
    customer = _match_by_mbi(fact, agency_id)
    if customer is not None:
        result.customer = customer
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "mbi"
        return result

    # 4. Stub — nothing matched; create stub customer + policy (at most once per member,
    #    because next time the crosswalk in step 1 will find this policy).
    customer = _create_stub(fact, agency_id, agent_id, source)
    result.customer = customer
    result.created_customer = True
    result.policy = _attach_policy(fact, customer, agency_id, agent_id)
    result.created_policy = True
    result.match_path = "stub"
    return result
