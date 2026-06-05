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
]

TRUST_ORDER = {"carrier_import": 1, "agent_entered": 2, "human_verified": 3}

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
    }
    _save(customer, data)
    customer.manually_edited = True
