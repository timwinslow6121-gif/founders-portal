"""
app/commission/resolver.py

The ONE identity codepath for both commission upload and BOB upload. Turns a
MemberFact into a resolved (Customer, Policy) with lifecycle side effects
(carrier-switch terming, new AOR interval, rapid_disenroll flag) and, when it
cannot confidently match, a stub + a MatchSuggestion for human confirm.

Resolution order: crosswalk (Policy by carrier+member_id) → MBI → suggest-link →
stub. See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §2.
"""
import json
from dataclasses import dataclass, field
from typing import Optional, List

from app.extensions import db
from app.models import Customer, Policy, CustomerAorHistory, MatchSuggestion
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


def _apply_rapid_disenroll(policy: Policy, fact: MemberFact, result: ResolveResult):
    eff, term = fact.effective_date, fact.term_date
    if eff and term and (term - eff).days < 90:
        policy.rapid_disenroll = True
        result.actions.append("rapid_disenroll")


def _apply_carrier_switch(fact: MemberFact, customer: Customer, new_policy: Policy,
                          agency_id: int, agent_id, result: ResolveResult):
    """If customer has an active policy on a different carrier and this is an
    ENROLLMENT, term the old policy. (Same-carrier renewals are not switches.)"""
    if fact.row_class != RowClass.ENROLLMENT:
        return
    others = (Policy.query
              .filter(Policy.agency_id == agency_id,
                      Policy.customer_id == customer.id,
                      Policy.carrier != fact.carrier,
                      Policy.status == "active")
              .all())
    for old in others:
        old.status = "termed"
        old.new_carrier = fact.carrier
        if not old.term_date and fact.effective_date:
            old.term_date = fact.effective_date
        result.actions.append("carrier_switch")


def _open_aor_interval(fact: MemberFact, customer: Customer, agency_id: int,
                       agent_id, batch_id, result: ResolveResult):
    """Open an AOR interval if none exists for this customer+carrier+effective_date.
    BCBS term_date is a renewal date — never an end_date."""
    if not fact.effective_date:
        return
    existing = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=fact.carrier, effective_date=fact.effective_date,
    ).first()
    if existing:
        return
    end_date = None if fact.carrier == "BCBS" else fact.term_date
    aor = CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=agent_id,
        carrier=fact.carrier, plan_name=None, effective_date=fact.effective_date,
        end_date=end_date, source=result.match_path or "commission_import",
        import_batch_id=batch_id,
    )
    db.session.add(aor)
    result.actions.append("aor_interval")


def _find_name_dob_match(fact: MemberFact, agency_id: int):
    """Return (customer, confidence) for a name+DOB near-match, else (None, None).
    Only fires when DOB is present (BCBS rows have no DOB, so they won't match
    until DOB exists from a prior BOB record/edit)."""
    fn = (fact.first_name or "").strip().lower()
    ln = (fact.last_name or "").strip().lower()
    if not fn or not ln or not fact.dob:
        return None, None
    c = (Customer.query
         .filter(Customer.agency_id == agency_id,
                 db.func.lower(Customer.first_name) == fn,
                 db.func.lower(Customer.last_name) == ln,
                 Customer.dob == fact.dob)
         .first())
    if c:
        return c, "name_dob"
    return None, None


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
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result)
        return result

    # 3. Suggest-link — no crosswalk, no MBI, but a name+DOB near-match exists.
    #    Create a stub (so no payment is lost) AND a MatchSuggestion for human confirm.
    candidate, confidence = _find_name_dob_match(fact, agency_id)
    if candidate is not None:
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer
        result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "suggest_link"
        ms = MatchSuggestion(
            agency_id=agency_id,
            stub_customer_id=customer.id,
            suggested_customer_id=candidate.id,
            confidence=confidence,
            status="pending",
            source_member_fact_json=json.dumps({
                "carrier": fact.carrier, "carrier_member_id": fact.carrier_member_id,
                "full_name": fact.full_name, "dob": fact.dob.isoformat() if fact.dob else None,
            }),
        )
        db.session.add(ms)
        result.actions.append("match_suggestion")
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result)
        return result

    # 4. Stub — nothing matched; create stub customer + policy (at most once per member,
    #    because next time the crosswalk in step 1 will find this policy).
    customer = _create_stub(fact, agency_id, agent_id, source)
    result.customer = customer
    result.created_customer = True
    result.policy = _attach_policy(fact, customer, agency_id, agent_id)
    result.created_policy = True
    result.match_path = "stub"
    _apply_rapid_disenroll(result.policy, fact, result)
    _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
    _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result)
    return result
