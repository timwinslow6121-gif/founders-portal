"""
app/commission/ingest.py

The single per-statement commission pipeline: normalize a carrier file into
MemberFacts, resolve each to a Customer/Policy/AOR (Plan 2 resolver), and write a
PolicyPayment linked to the resolved policy — in one pass. Plus a statement
fingerprint for duplicate detection.

See docs/superpowers/specs/2026-06-03-commission-customer-sync-design.md §4.
"""
from dataclasses import dataclass, field
from typing import List, Optional
import hashlib

from app.extensions import db
from app.models import PolicyPayment
from app.commission.member_fact import MemberFact, RowClass
from app.commission.resolver import resolve_customer
from app.commission.payments import _norm


def _payment_key(fact: MemberFact):
    """Stable identity of a payment row within a statement."""
    return (fact.carrier_member_id or fact.mbi or _norm(fact.full_name) or "").strip()


def write_payment_from_fact(fact: MemberFact, statement, policy, agency_id: int,
                            agent_id: Optional[int]) -> PolicyPayment:
    """Insert or update (in place) a PolicyPayment for this fact within the statement."""
    key = _payment_key(fact)
    action = fact.row_class  # canonical: enrollment|renewal|chargeback|non_customer
    norm_name = _norm(fact.full_name)
    source_ref = (fact.source_ref or "").strip() or None

    if source_ref:
        # Preferred: stable per-row provenance key. NON_CUSTOMER (HRA) rows have no
        # member identity and degenerate to the same normalized name, so name/id
        # matching would false-merge them — source_ref keeps them distinct while
        # still updating in place on re-ingest.
        existing = (PolicyPayment.query
                    .filter_by(statement_id=statement.id, agency_id=agency_id,
                               source_ref=source_ref)
                    .first())
    else:
        existing = (PolicyPayment.query
                    .filter_by(statement_id=statement.id, agency_id=agency_id,
                               commission_action=action)
                    .filter((PolicyPayment.carrier_member_id == (fact.carrier_member_id or None)) |
                            (PolicyPayment.mbi == (fact.mbi or None)) |
                            (PolicyPayment.member_name_normalized == norm_name))
                    .first()) if key else None

    if existing is None:
        existing = PolicyPayment(
            agency_id=agency_id,
            statement_id=statement.id,
            carrier=fact.carrier,
            period_label=statement.period_label,
            statement_date=statement.statement_date,
            member_name=fact.full_name,
            commission_action=action,
            paid_amount=0.0,
        )
        db.session.add(existing)

    existing.agent_id = agent_id
    existing.source_ref = source_ref
    existing.member_name = fact.full_name
    existing.member_name_normalized = norm_name
    existing.mbi = fact.mbi
    existing.carrier_member_id = fact.carrier_member_id
    existing.policy_id = policy.id if policy is not None else None
    if policy is None:
        existing.match_confidence = "unmatched"
    else:
        existing.match_confidence = "exact" if (fact.mbi or fact.carrier_member_id) else "name"
    existing.commission_action = action
    existing.paid_amount = fact.amount
    existing.is_chargeback = fact.amount < 0
    existing.effective_date = fact.effective_date
    existing.term_date = fact.term_date
    existing.plan_name = None
    return existing


def compute_fingerprint(carrier: str, period_label: str, facts: List[MemberFact]) -> str:
    """A stable, order-independent signature of a statement's CONTENT. Used to
    detect an exact re-upload. Sensitive to row count, the set of member ids, and
    the summed amount — so a corrected re-pull (different totals) is NOT mistaken
    for an exact duplicate.

    ``period_label`` is intentionally EXCLUDED from the hash: the same file can be
    detected at a drifted period (e.g. June vs May from a parser fix), and the
    duplicate guard must still catch it as the same content. The param is kept in
    the signature only for call-site compatibility."""
    total = round(sum(f.amount for f in facts), 2)
    ids = sorted((f.carrier_member_id or f.mbi or _norm(f.full_name) or "") for f in facts)
    h = hashlib.sha256()
    h.update(f"{carrier}|{len(facts)}|{total}|{'|'.join(ids)}".encode())
    return h.hexdigest()


@dataclass
class IngestResult:
    fingerprint: str = ""
    facts_total: int = 0
    customers_created: int = 0
    stubs_created: int = 0
    payments_written: int = 0
    chargebacks: int = 0
    match_suggestions: int = 0
    carrier_switches: int = 0
    parked_payments: int = 0
    gross: float = 0.0
    actions: List[str] = field(default_factory=list)


# Carriers handled by the new normalize→resolve pipeline. UHC stays on the legacy
# parser until Plan 6 (lumped LOA split).
from app.commission.normalizers import NORMALIZERS


def ingest_statement(statement, carrier: str, agent_id, agency_id: int, sheets,
                     agent_resolver=None) -> IngestResult:
    """Normalize a carrier file → resolve each fact → write payments. One pass.

    Agency-level carriers (Devoted/Healthspring/Aetna) name a writing agent per
    row on the MemberFact. When ``agent_resolver`` (a callable raw_name -> user_id
    or None) is supplied, each row's agent is resolved from ``writing_agent_raw``,
    falling back to the statement-level ``agent_id``. When None, ``agent_id`` is
    used for every row (backward compatible)."""
    result = IngestResult()
    normalizer = NORMALIZERS.get(carrier)
    if normalizer is None:
        return result

    facts = normalizer(sheets)
    result.facts_total = len(facts)
    result.fingerprint = compute_fingerprint(carrier, statement.period_label, facts)
    result.gross = round(sum(f.amount for f in facts), 2)

    for fact in facts:
        row_agent_id = agent_id
        if agent_resolver is not None:
            raw = (getattr(fact, "writing_agent_raw", "") or "").strip()
            if raw:
                resolved = agent_resolver(raw)
                if resolved:
                    row_agent_id = resolved

        if fact.row_class == RowClass.NON_CUSTOMER:
            write_payment_from_fact(fact, statement, None, agency_id, row_agent_id)
            result.payments_written += 1
            if fact.amount < 0:
                result.chargebacks += 1
            continue

        res = resolve_customer(fact, agency_id=agency_id, agent_id=row_agent_id,
                               source="commission_import")
        if res.created_customer:
            result.customers_created += 1
            if res.customer is not None and res.customer.stub:
                result.stubs_created += 1
        if "match_suggestion" in res.actions:
            result.match_suggestions += 1
        if "carrier_switch" in res.actions:
            result.carrier_switches += 1
        if res.match_path == "parked":
            result.parked_payments += 1

        write_payment_from_fact(fact, statement, res.policy, agency_id, row_agent_id)
        result.payments_written += 1
        if fact.amount < 0:
            result.chargebacks += 1

    db.session.flush()
    return result
