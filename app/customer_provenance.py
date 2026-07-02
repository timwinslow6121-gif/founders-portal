"""
app/customer_provenance.py

Per-field provenance + precedence for Customer, the sibling of app/plan_provenance.py
(shared pattern, not shared code). The single seam: ALL reads/writes of per-field
_meta/_conflicts go through this module; nothing else touches customers.field_provenance.

Storage: customers.field_provenance is a JSON blob:
  {
    "_meta": { field: {value, source, trust, updated_at, updated_by, history:[...] } },
    "_conflicts": [ {field, existing:{value,source,by,at}, incoming:{value,source,at},
                     flagged_at, resolved, resolved_by, resolved_at, resolution} ]
  }
Customer field values are PLAIN SCALARS (strings / ISO date strings), not the
{amount,period,unit} shape plan benefits use.

Trust order: human_verified > agent_entered > carrier_import > empty.
See docs/superpowers/specs/2026-06-05-customer-provenance-engine-design.md.
"""
import json
from datetime import datetime, date

PROVENANCE_FIELDS = [
    "mbi", "humana_id", "first_name", "last_name", "dob", "gender",
    "phone_primary", "phone_secondary", "email", "address1", "city",
    "state", "zip_code", "county", "medicaid_level", "medicaid_id",
    "preferred_name",
]

TRUST_ORDER = {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}

__all__ = [
    "PROVENANCE_FIELDS", "TRUST_ORDER",
    "get_field", "trust_of",
    "set_human_value", "set_import_value",
    "list_conflicts", "resolve_conflict",
]

# source strings (trust tier in parens): agent_edit(agent_entered),
# aj_verified(human_verified), bob_import/commission_import/healthsherpa(carrier_import)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def _load(customer):
    if not customer.field_provenance:
        return {}
    try:
        return json.loads(customer.field_provenance)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save(customer, data):
    customer.field_provenance = json.dumps(data)


def _to_scalar(value):
    """Normalize a field value to a JSON-serializable scalar for storage/compare."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def get_field(customer, field):
    """Full provenance record for a field, or None."""
    rec = _load(customer).get("_meta", {}).get(field)
    return rec if rec else None


def trust_of(customer, field):
    rec = get_field(customer, field)
    return rec.get("trust") if rec else None


def _set_column(customer, field, value):
    """Write the real typed column. dob is the only date field; others are strings."""
    if field == "dob" and isinstance(value, str) and value:
        try:
            value = date.fromisoformat(value)
        except ValueError:
            pass
    setattr(customer, field, value)


def set_human_value(customer, field, value, user, note=None, verify=False):
    """Apply a human edit (agent) or verification (verify=True -> AJ).

    Writes the real column AND _meta, appends history, sets manually_edited=True.
    `value` may be a scalar or a date; stored as a scalar in _meta.
    """
    if field not in PROVENANCE_FIELDS:
        raise ValueError(f"{field} is not a provenance-tracked field")

    _set_column(customer, field, value)
    scalar = _to_scalar(value)

    data = _load(customer)
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value")
    history = meta.get(field, {}).get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": prev, "to": scalar, "note": note})
    meta[field] = {
        "value": scalar,
        "source": "aj_verified" if verify else "agent_edit",
        "trust": "human_verified" if verify else "agent_entered",
        "updated_at": _now(),
        "updated_by": getattr(user, "name", None),
        "history": history,
        "rejected_values": [],
    }
    _save(customer, data)
    customer.manually_edited = True


def _is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def _flag_conflict(data, customer, field, existing, incoming_scalar, source):
    """Append one open conflict per field (idempotent — mirrors plan_provenance)."""
    conflicts = data.setdefault("_conflicts", [])
    for c in conflicts:
        if c["field"] == field and not c.get("resolved"):
            return
    conflicts.append({
        "field": field,
        "existing": {
            "value": existing.get("value"),
            "source": existing.get("source"),
            "by": existing.get("updated_by"),
            "at": existing.get("updated_at"),
        },
        "incoming": {"value": incoming_scalar, "source": source, "at": _now()},
        "flagged_at": _now(),
        "resolved": False, "resolved_by": None, "resolved_at": None, "resolution": None,
    })


def set_import_value(customer, field, value, source):
    """Apply an import-sourced value using precedence. Returns:
    'skipped' | 'written' | 'confirmed' | 'conflict_flagged'.

    Never overwrites an agent_entered/human_verified value (flags a conflict).
    A differing carrier-tier value is overwritten (newer carrier wins).
    """
    if field not in PROVENANCE_FIELDS:
        raise ValueError(f"{field} is not a provenance-tracked field")
    if _is_blank(value):
        return "skipped"

    scalar = _to_scalar(value)
    data = _load(customer)
    meta = data.setdefault("_meta", {})
    existing = meta.get(field)

    def _write(action, prev=None):
        history = (existing or {}).get("history", [])
        history.append({"at": _now(), "by": None, "from": prev, "to": scalar,
                        "note": f"import:{source}"})
        meta[field] = {
            "value": scalar, "source": source, "trust": "carrier_import",
            "updated_at": _now(), "updated_by": None, "history": history,
        }
        _set_column(customer, field, value)
        _save(customer, data)
        return action

    if existing is None:
        return _write("written")

    prev = existing.get("value")
    same = (prev == scalar)
    trust = existing.get("trust")

    if same:
        existing["updated_at"] = _now()
        _save(customer, data)
        return "confirmed"

    if trust in ("agent_entered", "human_verified"):
        rejected = existing.get("rejected_values", [])
        if scalar in rejected:
            existing.setdefault("history", []).append(
                {"at": _now(), "by": None, "from": existing.get("value"),
                 "to": scalar, "note": f"import:{source} suppressed (previously rejected)"})
            _save(customer, data)
            return "suppressed"
        _flag_conflict(data, customer, field, existing, scalar, source)
        _save(customer, data)
        customer.has_unresolved_conflicts = True
        return "conflict_flagged"

    # carrier_import tier and differs -> newer carrier wins
    return _write("written", prev=prev)


def list_conflicts(customer, unresolved_only=True):
    conflicts = _load(customer).get("_conflicts", [])
    if unresolved_only:
        return [c for c in conflicts if not c.get("resolved")]
    return conflicts


def resolve_conflict(customer, field, choose, user, note=None):
    """Resolve a field conflict. choose in {'keep_current', 'take_incoming'}.

    The surviving value is written as human_verified (a resolution is a human
    decision). Marks the conflict resolved and recomputes has_unresolved_conflicts.
    """
    if choose not in ("keep_current", "take_incoming"):
        raise ValueError("choose must be 'keep_current' or 'take_incoming'")

    data = _load(customer)
    meta = data.setdefault("_meta", {})
    rec = meta.get(field, {})
    current = rec.get("value")

    conflict = next((c for c in data.get("_conflicts", [])
                     if c["field"] == field and not c.get("resolved")), None)
    if conflict is None:
        return  # nothing to resolve — safe no-op (don't write meta or touch the column)
    incoming = conflict["incoming"]["value"] if conflict else None

    surviving = current if choose == "keep_current" else incoming

    prior_rejected = rec.get("rejected_values", [])
    if choose == "keep_current" and incoming is not None and incoming not in prior_rejected:
        prior_rejected = prior_rejected + [incoming]

    history = rec.get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": current, "to": surviving,
                    "note": note or f"conflict resolved ({choose})"})
    meta[field] = {
        "value": surviving, "source": "aj_verified", "trust": "human_verified",
        "updated_at": _now(), "updated_by": getattr(user, "name", None),
        "history": history,
        "rejected_values": prior_rejected,
    }
    _set_column(customer, field, surviving)

    for c in data.get("_conflicts", []):
        if c["field"] == field and not c.get("resolved"):
            c["resolved"] = True
            c["resolved_by"] = getattr(user, "name", None)
            c["resolved_at"] = _now()
            c["resolution"] = choose
    _save(customer, data)
    remaining = [c for c in data.get("_conflicts", []) if not c.get("resolved")]
    customer.has_unresolved_conflicts = bool(remaining)
