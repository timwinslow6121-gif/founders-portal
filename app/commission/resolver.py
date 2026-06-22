"""
app/commission/resolver.py

The ONE identity codepath for both commission upload and BOB upload. Turns a
MemberFact into a resolved (Customer, Policy) with lifecycle side effects
(carrier-switch terming, new AOR interval, rapid_disenroll flag) and, when it
cannot confidently match, a stub + a MatchSuggestion for human confirm.

Resolution order: crosswalk (Policy by carrier+member_id) → MBI → carrier_member_id
(existing Policy by carrier+member_id with a different effective id shape) →
suggest-link → stub. See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §2.
"""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
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


def _match_by_carrier_member_id(fact: MemberFact, agency_id: int):
    """Return the Customer of an existing active Policy whose (carrier, member_id)
    equals this fact's (carrier, carrier_member_id). Resolves commission rows that
    carry the carrier's member id but no MBI (the matcher previously only tried MBI).
    no_autoflush: must not autoflush a pending stub mid-import."""
    cmid = (fact.carrier_member_id or "").strip()
    if not cmid:
        return None
    with db.session.no_autoflush:
        p = (Policy.query
             .filter_by(carrier=fact.carrier, member_id=cmid, agency_id=agency_id,
                        status="active")
             .filter(Policy.customer_id.isnot(None))
             .first())
    return Customer.query.get(p.customer_id) if p else None


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


def _supersedes(incoming: CustomerAorHistory, existing: CustomerAorHistory) -> bool:
    """Phase 1 supersession predicate (the heart of AOR reconciliation).

    Return True when `incoming` (a just-opened ENROLLMENT interval) should END-DATE
    the already-persisted `existing` interval. Both are the SAME (customer, carrier)
    by construction; this decides the date relationship + guardrails.

    Guardrails from the spec (§2.B / §5) and Tim's §7 answers — only end-date an
    interval that is:
      - still OPEN (existing.end_date is None) — never re-close history, and
      - strictly EARLIER-effective than the incoming enrollment
        (existing.effective_date < incoming.effective_date) — a newer enrollment
        supersedes an older one, never the reverse, and never an equal/same-day row.
    BCBS is already excluded upstream (its term_date is a renewal date, not an end),
    so this predicate does not need a carrier check.

    """
    if existing.end_date is not None:
        return False                       # already closed — never re-close history
    if existing.effective_date is None or incoming.effective_date is None:
        return False                       # can't prove which is older → leave it
    return existing.effective_date < incoming.effective_date


def _aor_close_date(incoming_eff: date, term_date: Optional[date]) -> date:
    """The date to close a superseded interval at. Tim's §7: use the row's term_date
    when present (carrier-authoritative, already month-end); otherwise the day before
    the new effective date (Medicare effs are the 1st, so new_eff−1 lands on month-end,
    e.g. 6/1 → 5/31)."""
    return term_date if term_date is not None else incoming_eff - timedelta(days=1)


def _open_aor_interval(fact: MemberFact, customer: Customer, agency_id: int,
                       agent_id, batch_id, result: ResolveResult, source: str):
    """Phase 1 AOR reconciliation. Opens an interval and reconciles the timeline:

      - Bootstrap: if NO open interval exists for (customer, carrier), open one for
        ANY row (so BOB renewals + first sales still get their initial interval).
      - Otherwise only ENROLLMENT rows open a new interval; renewals/chargebacks just
        confirm the existing coverage (prevents the per-row duplicate intervals).
      - When an ENROLLMENT opens a later interval, close every OPEN, strictly-earlier
        interval for the same (customer, carrier) — the Tocara supersession rule.

    BCBS term_date is a renewal date — never an end_date. `source` is recorded for
    provenance; plan_name is carried so BOB plan names are preserved."""
    if not fact.effective_date:
        return
    # No real agent resolved → the customer is UNASSIGNED. Don't fabricate an AOR
    # interval (agent_id is NOT NULL); the AOR is created when an agent is assigned.
    if agent_id is None:
        return

    # Exact-duplicate guard: an identical (carrier, effective_date) interval already
    # exists — never create a second copy of the same coverage.
    existing_same = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=fact.carrier, effective_date=fact.effective_date,
    ).first()
    if existing_same:
        return

    open_intervals = CustomerAorHistory.query.filter_by(
        customer_id=customer.id, carrier=fact.carrier, end_date=None,
    ).all()

    # Gate: only ENROLLMENT opens additional intervals; but if the customer has NO
    # open interval for this carrier yet, bootstrap the first one from any row.
    from app.commission.member_fact import RowClass
    if open_intervals and fact.row_class != RowClass.ENROLLMENT:
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

    # Supersede older open intervals (BCBS excluded — its end_date is never a term).
    if fact.carrier != "BCBS":
        for prior in open_intervals:
            if _supersedes(aor, prior):
                prior.end_date = _aor_close_date(fact.effective_date, fact.term_date)
                result.actions.append("aor_superseded")


def _enqueue_suggestion(fact: MemberFact, stub_customer: Optional[Customer],
                        candidate: Optional[Customer], confidence, agency_id: int,
                        result: ResolveResult):
    """Record a MatchSuggestion for human confirm (no automerge).

    NULL-tolerant: the §6 weak-identity tail calls this with stub_customer=None
    AND candidate=None (no customer was created at all — nothing to link yet,
    the hub triages from the fact JSON alone). Both FK columns are nullable."""
    ms = MatchSuggestion(
        agency_id=agency_id,
        stub_customer_id=stub_customer.id if stub_customer else None,
        suggested_customer_id=candidate.id if candidate else None,
        confidence=confidence,
        status="pending",
        source_member_fact_json=json.dumps({
            "carrier": fact.carrier, "carrier_member_id": fact.carrier_member_id,
            "full_name": fact.full_name, "dob": fact.dob.isoformat() if fact.dob else None,
            "amount": fact.amount, "writing_agent_raw": fact.writing_agent_raw,
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


def _composite_match(fact: MemberFact, agency_id: int):
    """Auto-match tier: name + DOB + at least one corroborating field (zip/phone).
    Name+DOB alone is NOT enough (the prevention boundary — see §6). Returns
    (customer, 'composite') or (None, None).

    no_autoflush: see _crosswalk — must not autoflush a pending stub mid-import."""
    fn = (fact.first_name or "").strip().lower()
    ln = (fact.last_name or "").strip().lower()
    if not fn or not ln or not fact.dob:
        return None, None
    corrob_zip = (getattr(fact, "zip_code", None) or "").strip() or None
    phone = (getattr(fact, "phone", None) or "").strip() or None
    if not corrob_zip and not phone:
        return None, None      # name+dob only → not enough
    with db.session.no_autoflush:
        q = (Customer.query.filter(
                Customer.agency_id == agency_id,
                db.func.lower(Customer.first_name) == fn,
                db.func.lower(Customer.last_name) == ln,
                Customer.dob == fact.dob))
        if corrob_zip:
            q = q.filter(Customer.zip_code == corrob_zip)
        if phone:
            q = q.filter(Customer.phone_primary == phone)
        c = q.first()
    return (c, "composite") if c else (None, None)


def has_strong_identity(fact: MemberFact, agency_id: Optional[int] = None) -> bool:
    """True if the fact carries an MBI, a carrier_member_id, or (when agency_id
    given) a composite match exists. Used by the §6 prevention tail to decide
    create-vs-queue on the final no-match branch."""
    if (fact.mbi or "").strip() or (fact.carrier_member_id or "").strip():
        return True
    if agency_id is not None:
        c, _ = _composite_match(fact, agency_id)
        return c is not None
    return False


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

    # 2b. carrier_member_id match — a real carrier id is as good as an MBI.
    customer = _match_by_carrier_member_id(fact, agency_id)
    if customer is not None:
        result.customer = customer
        existing = _crosswalk(fact, agency_id)
        if existing is not None:
            existing.customer_id = existing.customer_id or customer.id
            result.policy = existing
        else:
            result.policy = _attach_policy(fact, customer, agency_id, agent_id)
            result.created_policy = True
        result.match_path = "carrier_member_id"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 3. Composite auto-match (name+DOB+corroborating field) — adopt, no queue.
    cand, conf = _composite_match(fact, agency_id)
    if cand is not None:
        result.customer = cand
        result.policy = _attach_policy(fact, cand, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "composite"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 4. Name+DOB-only near-match → suggest-link (stub + MatchSuggestion for human confirm).
    candidate, confidence = _find_name_dob_match(fact, agency_id)
    if candidate is not None:
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer; result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "suggest_link"
        _enqueue_suggestion(fact, customer, candidate, confidence, agency_id, result)
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # 5. No candidate. §6 boundary: strong identity → create (legit new-to-Medicare);
    #    weak identity → enqueue a needs-match item, NO phantom policy.
    if has_strong_identity(fact):
        customer = _create_stub(fact, agency_id, agent_id, source)
        result.customer = customer; result.created_customer = True
        result.policy = _attach_policy(fact, customer, agency_id, agent_id)
        result.created_policy = True
        result.match_path = "new_strong"
        _apply_rapid_disenroll(result.policy, fact, result)
        _apply_carrier_switch(fact, result.customer, result.policy, agency_id, agent_id, result)
        _open_aor_interval(fact, result.customer, agency_id, agent_id, batch_id, result, source)
        return result

    # weak identity → no policy; enqueue with full info for the hub
    _enqueue_suggestion(fact, None, None, "weak_identity", agency_id, result)
    result.match_path = "needs_identity"
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
