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

__all__ = ["resolve_customer", "ResolveResult", "member_fact_from_bob_rec"]


@dataclass
class ResolveResult:
    customer: Optional[Customer] = None
    policy: Optional[Policy] = None
    created_customer: bool = False
    created_policy: bool = False
    match_path: str = ""           # crosswalk | mbi | suggest_link | stub
    actions: List[str] = field(default_factory=list)


def _effective_member_id(fact: MemberFact) -> str:
    """The Policy.member_id for this fact: carrier id, else MBI, else the
    per-row source_ref (so rows lacking both still get a UNIQUE member_id and
    are never collapsed/collided).

    TRADEOFF: source_ref encodes the row INDEX (e.g. "humana::...::226"). For
    rows with no carrier id/MBI, the crosswalk re-link on re-upload therefore
    depends on the row landing at the same index. Acceptable for these rare
    no-id rows (better than a crash or an empty-string collision); carrier-id/
    MBI rows are unaffected — they still key on their stable id."""
    return (fact.carrier_member_id or fact.mbi or fact.source_ref or "").strip()


def _crosswalk(fact: MemberFact, agency_id: int):
    """Return existing Policy matched by (carrier, effective member_id), else None.
    The effective member_id mirrors _attach_policy: carrier_member_id, else MBI,
    else source_ref.

    no_autoflush: a stub Customer/Policy created earlier in this SAME uncommitted
    transaction (another row of the same file) must NOT be autoflushed by THIS
    SELECT — that flush would fire ix_customers_mbi and crash the whole upload.
    The match queries are pure reads; suppressing autoflush is safe."""
    cid = _effective_member_id(fact)
    if not cid:
        return None
    with db.session.no_autoflush:
        return (Policy.query
                .filter_by(agency_id=agency_id, carrier=fact.carrier, member_id=cid)
                .first())


def _attach_policy(fact: MemberFact, customer: Customer, agency_id: int,
                   agent_id: Optional[int]) -> Policy:
    """Create a Policy for this fact linked to the given customer."""
    p = Policy(
        agency_id=agency_id,
        carrier=fact.carrier,
        member_id=_effective_member_id(fact),
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
    """Return existing Customer by MBI (or humana_id for Humana), else None.

    no_autoflush (see _crosswalk): this SELECT must not autoflush a pending stub
    INSERT and trip ix_customers_mbi mid-upload."""
    with db.session.no_autoflush:
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
                       agent_id, batch_id, result: ResolveResult, source: str):
    """Open an AOR interval if none exists for this customer+carrier+effective_date.
    BCBS term_date is a renewal date — never an end_date. The `source` (e.g. "bob"
    or "commission_import") is recorded for provenance, and plan_name is carried
    from the fact so BOB plan names are preserved."""
    if not fact.effective_date:
        return
    # No real agent resolved → the customer is UNASSIGNED. Don't fabricate an AOR
    # interval (agent_id is NOT NULL); the AOR is created when an agent is assigned.
    if agent_id is None:
        return
    existing = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=fact.carrier, effective_date=fact.effective_date,
    ).first()
    if existing:
        return
    end_date = None if fact.carrier == "BCBS" else fact.term_date
    aor = CustomerAorHistory(
        agency_id=agency_id, customer_id=customer.id, agent_id=agent_id,
        carrier=fact.carrier, plan_name=fact.plan_name, effective_date=fact.effective_date,
        end_date=end_date, source=source or "commission_import",
        import_batch_id=batch_id,
    )
    db.session.add(aor)
    result.actions.append("aor_interval")


def _enqueue_suggestion(fact: MemberFact, stub_customer: Customer, candidate: Customer,
                        confidence, agency_id: int, result: ResolveResult):
    """Record a MatchSuggestion for human confirm (no automerge)."""
    ms = MatchSuggestion(
        agency_id=agency_id,
        stub_customer_id=stub_customer.id,
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


def _find_name_dob_match(fact: MemberFact, agency_id: int):
    """Return (customer, confidence) for a name+DOB near-match, else (None, None).
    Only fires when DOB is present (BCBS rows have no DOB, so they won't match
    until DOB exists from a prior BOB record/edit)."""
    fn = (fact.first_name or "").strip().lower()
    ln = (fact.last_name or "").strip().lower()
    if not fn or not ln or not fact.dob:
        return None, None
    with db.session.no_autoflush:   # see _crosswalk — don't autoflush a pending stub
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

    # 1. Crosswalk — deterministic re-link. A policy may already exist either from a
    #    prior import OR from the BOB outer loop that just added it this same flow.
    #    ALWAYS adopt a found policy — never fall through and create a duplicate.
    policy = _crosswalk(fact, agency_id)
    if policy is not None:
        result.policy = policy
        result.match_path = "crosswalk"
        customer = Customer.query.get(policy.customer_id) if policy.customer_id else None
        if customer is None:
            # Outer-loop policy with no customer yet, OR legacy policy: resolve the
            # customer by MBI/humana/name+DOB, else create a stub, then link the policy.
            customer = _match_by_mbi(fact, agency_id)
            match_path = "mbi" if customer is not None else None
            if customer is None:
                cand, conf = _find_name_dob_match(fact, agency_id)
                if cand is not None:
                    customer = _create_stub(fact, agency_id, agent_id, source)
                    result.created_customer = True
                    _enqueue_suggestion(fact, customer, cand, conf, agency_id, result)
                    match_path = "suggest_link"
            if customer is None:
                customer = _create_stub(fact, agency_id, agent_id, source)
                result.created_customer = True
                match_path = "stub"
            policy.customer_id = customer.id
            result.match_path = match_path or "crosswalk"
        result.customer = customer
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 2. MBI / humana_id match
    customer = _match_by_mbi(fact, agency_id)
    if customer is not None:
        result.customer = customer
        existing = _crosswalk(fact, agency_id)
        if existing is not None:
            existing.customer_id = existing.customer_id or customer.id
            result.policy = existing
        else:
            result.policy = _attach_policy(fact, customer, agency_id, agent_id)
            result.created_policy = True
        result.match_path = "mbi"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
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
        _enqueue_suggestion(fact, customer, candidate, confidence, agency_id, result)
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
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
    _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
    return result


def member_fact_from_bob_rec(rec: dict) -> MemberFact:
    """Adapt a BOB upload `rec` dict to a MemberFact so BOB upload can route
    through the same resolver. BOB rows are enrollments/renewals (never commission
    chargeback rows), so row_class defaults to RENEWAL — the resolver's lifecycle
    handles interval opening."""
    carrier = rec.get("carrier", "")
    return MemberFact(
        carrier=carrier,
        full_name=rec.get("full_name") or f"{rec.get('first_name','')} {rec.get('last_name','')}".strip(),
        first_name=rec.get("first_name") or "",
        last_name=rec.get("last_name") or "",
        mbi=(rec.get("mbi") or None),
        carrier_member_id=(rec.get("member_id") or None),
        dob=rec.get("dob"),
        effective_date=rec.get("effective_date"),
        term_date=rec.get("term_date"),
        plan_type=rec.get("plan_type"),
        plan_name=rec.get("plan_name"),
        row_class=RowClass.RENEWAL,
        amount=0.0,
    )
