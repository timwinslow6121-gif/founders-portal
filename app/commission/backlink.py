"""
Shared customer back-link resolution for commission ledger rows.

WHY THIS EXISTS: `persist_line_items` used to resolve its customer link with a
single-tier MBI dictionary, which was strictly weaker than the resolver
`policy_payments` already uses at ingest — and it assigned unconditionally, so a
miss ERASED an existing link. BCBS went 213/213 (May) -> 199/216 (June) ->
0/218 (July) as re-uploads wiped prior links, because BCBS commission rows carry
NO MBI at all (only `carrier_member_id`).

RESOLUTION ORDER (see docs/superpowers/specs/2026-08-06-ledger-customer-backlink-repair-design.md):
  1. source_ref -> PolicyPayment -> Policy.customer_id. The payment sibling
     already resolved at ingest with the full tier stack + the carrier crosswalk,
     so the ledger INHERITS its answer and the two tables cannot diverge.
     Measured: recovers 537 of 641, a strict superset of re-resolving.
  2. Fall back to the shared `_match_policy` resolver (MBI -> carrier_member_id ->
     fuzzy name) for rows with no payment sibling — notably UHC's decomposed
     `::r`/`::o` refs, which have no payment counterpart by construction.
  3. Return None. The CALLER must leave any existing customer_id alone.
"""

from app.extensions import db
from app.models import Policy, PolicyPayment


class BacklinkContext:
    """Prebuilt lookup maps for one agency. Build ONCE per statement, not per row."""

    __slots__ = ("agency_id", "by_source_ref", "mbi_map", "carrier_id_map", "name_map")

    def __init__(self, agency_id, by_source_ref, mbi_map, carrier_id_map, name_map):
        self.agency_id = agency_id
        self.by_source_ref = by_source_ref
        self.mbi_map = mbi_map
        self.carrier_id_map = carrier_id_map
        self.name_map = name_map


def build_backlink_context(agency_id):
    """Build the agency-scoped lookup maps used by resolve_customer_id()."""
    from app.commission.payments import _build_name_index

    # Step-1 map: source_ref -> customer_id, via the already-resolved payment row.
    by_source_ref = {}
    rows = (db.session.query(PolicyPayment.source_ref, Policy.customer_id)
            .join(Policy, Policy.id == PolicyPayment.policy_id)
            .filter(PolicyPayment.agency_id == agency_id,
                    PolicyPayment.source_ref.isnot(None),
                    Policy.customer_id.isnot(None))
            .all())
    for sref, cust_id in rows:
        if sref:
            by_source_ref[sref] = cust_id

    # Step-2 maps: mirror what payments.build_payments() builds for _match_policy.
    all_policies = (Policy.query
                    .filter_by(agency_id=agency_id, status="active")
                    .with_entities(Policy.id, Policy.full_name, Policy.mbi,
                                   Policy.member_id, Policy.carrier)
                    .all())
    mbi_map = {p.mbi: p.id for p in all_policies if p.mbi}
    carrier_id_map = {(p.carrier, p.member_id): p.id
                      for p in all_policies if p.member_id}
    name_map = _build_name_index(agency_id)
    return BacklinkContext(agency_id, by_source_ref, mbi_map, carrier_id_map, name_map)


def resolve_customer_id(ctx, *, source_ref, carrier, mbi, carrier_member_id,
                        member_name):
    """Resolve one ledger row to a customer_id, or None.

    None means UNRESOLVED, not "clear the link" — the caller must leave any
    existing customer_id untouched (see the erasure bug in this module's docstring).
    """
    # 1. The payment sibling already did the work.
    sref = (source_ref or "").strip()
    if sref:
        hit = ctx.by_source_ref.get(sref)
        if hit is not None:
            return hit

    # 2. Fall back to the shared resolver, then policy -> customer.
    from app.commission.payments import _match_policy
    item = {"mbi": mbi or "", "carrier_member_id": carrier_member_id or "",
            "member_name": member_name or ""}
    policy_id, _confidence = _match_policy(item, carrier, ctx.agency_id,
                                           ctx.mbi_map, ctx.carrier_id_map,
                                           ctx.name_map)
    if policy_id is None:
        return None
    pol = (Policy.query
           .filter_by(id=policy_id, agency_id=ctx.agency_id)
           .with_entities(Policy.customer_id)
           .first())
    return pol.customer_id if pol else None
