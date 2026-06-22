"""Identity recovery orchestrator (spec 2026-06-22). The one seam for resolving a
record's identity via the confidence ladder, reusing app.commission.resolver matchers.
Auto-writes only on tier 1-3 (MBI / carrier_member_id / corroborated composite)."""
from app.extensions import db
from app.models import CommissionLineItem, Policy, Customer
from app.commission.member_fact import MemberFact
from app.commission.resolver import (_match_by_mbi, _match_by_carrier_member_id,
                                      _composite_match)


def _fact_from_line_item(li):
    nm = (li.member_name or "").strip()
    first = last = ""
    if "," in nm:
        last, first = [x.strip() for x in nm.split(",", 1)]
    elif nm:
        parts = nm.split()
        first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
    return MemberFact(carrier=li.carrier, full_name=nm, first_name=first, last_name=last,
                      mbi=li.mbi or None, carrier_member_id=li.carrier_member_id or None)


def resolve_payment_identity(line_item, agency_id):
    fact = _fact_from_line_item(line_item)
    cust = _match_by_mbi(fact, agency_id)
    tier = "mbi" if cust else None
    if cust is None:
        cust = _match_by_carrier_member_id(fact, agency_id)
        tier = "carrier_member_id" if cust else None
    if cust is None:
        cust, conf = _composite_match(fact, agency_id)
        tier = "composite" if cust else None
    if cust is None:
        return {"action": "queued", "customer_id": None, "tier": "none",
                "delete_stub_policy_id": None}
    line_item.customer_id = cust.id
    # If this payment spawned a uhc::N stub policy, signal it for deletion.
    stub = (Policy.query
            .filter(Policy.agency_id == agency_id,
                    Policy.member_id == line_item.source_ref).first())
    return {"action": "linked", "customer_id": cust.id, "tier": tier,
            "delete_stub_policy_id": (stub.id if stub and str(stub.member_id).startswith(line_item.carrier.lower()+"::") else None)}


def _titlecase(s):
    return " ".join(w.capitalize() for w in (s or "").split())


def recover_policy_name(policy, agency_id):
    if (policy.first_name or policy.last_name):
        return {"action": "skip", "source": "already named"}
    # ledger-first: a line item carrying this policy's identity + a member_name.
    # carrier_member_id is NOT globally unique — two carriers can issue the same
    # numeric member id — so that clause MUST be carrier-scoped, or a UHC policy
    # could pick up a Humana member's name. MBI IS globally unique, so its clause
    # is carrier-agnostic. Only OR in the mbi clause when policy.mbi is set —
    # otherwise `mbi == None` becomes `IS NULL` and matches every no-MBI line item.
    id_clause = ((CommissionLineItem.carrier_member_id == policy.member_id) &
                 (CommissionLineItem.carrier == policy.carrier))
    if policy.mbi:
        id_clause = id_clause | (CommissionLineItem.mbi == policy.mbi)
    li = (CommissionLineItem.query
          .filter(CommissionLineItem.agency_id == agency_id,
                  CommissionLineItem.member_name.isnot(None),
                  CommissionLineItem.member_name != "")
          .filter(id_clause)
          .order_by(CommissionLineItem.statement_date.desc().nullslast(),
                    CommissionLineItem.id.desc())   # deterministic: most recent wins
          .first())
    if not li:
        return {"action": "queued", "source": "no ledger name"}
    nm = li.member_name.strip()
    if "," in nm:
        last, first = [x.strip() for x in nm.split(",", 1)]
    else:
        parts = nm.split(); first = parts[0] if parts else ""; last = parts[-1] if len(parts) > 1 else ""
    policy.first_name = _titlecase(first); policy.last_name = _titlecase(last)
    policy.full_name = f"{policy.first_name} {policy.last_name}".strip()
    # also fill the customer if blank and not manually edited
    if policy.customer_id:
        c = db.session.get(Customer, policy.customer_id)
        if c and not c.manually_edited and not (c.first_name or c.last_name):
            c.first_name, c.last_name = policy.first_name, policy.last_name
            c.full_name = policy.full_name
    return {"action": "filled", "source": "ledger"}
