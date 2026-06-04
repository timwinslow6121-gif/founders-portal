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
    existing.member_name = fact.full_name
    existing.member_name_normalized = norm_name
    existing.mbi = fact.mbi
    existing.carrier_member_id = fact.carrier_member_id
    existing.policy_id = policy.id if policy is not None else None
    existing.match_confidence = "exact" if (fact.mbi or fact.carrier_member_id) else "name"
    existing.commission_action = action
    existing.paid_amount = fact.amount
    existing.is_chargeback = fact.amount < 0
    existing.effective_date = fact.effective_date
    existing.term_date = fact.term_date
    existing.plan_name = None
    return existing


def compute_fingerprint(carrier: str, period_label: str, facts: List[MemberFact]) -> str:
    """A stable, order-independent signature of a statement's content. Used to
    detect an exact re-upload. Sensitive to row count, the set of member ids, and
    the summed amount — so a corrected re-pull (different totals) is NOT mistaken
    for an exact duplicate."""
    total = round(sum(f.amount for f in facts), 2)
    ids = sorted((f.carrier_member_id or f.mbi or _norm(f.full_name) or "") for f in facts)
    h = hashlib.sha256()
    h.update(f"{carrier}|{period_label}|{len(facts)}|{total}|{'|'.join(ids)}".encode())
    return h.hexdigest()
