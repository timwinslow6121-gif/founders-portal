"""
app/plan_provenance.py

Provenance helper — the single seam owning structured benefit values and the
_meta / _conflicts provenance structure inside Plan.details_json.

Storage today is JSON-in-details_json. A future relational plan_benefit_values
table would change ONLY this module; callers (sync scripts, edit routes,
templates) use these functions and never touch the raw structure.

See docs/superpowers/specs/2026-06-02-plan-data-integrity-provenance-design.md
"""

_PERIOD_DISPLAY = {
    "mo": "/mo", "qtr": "/qtr", "yr": "/yr",
    "2yr": "/2yr", "3yr": "/3yr", "period": "/period", None: "",
}


def make_value(amount, period=None, unit="usd", display=None):
    """Build a structured benefit value dict.

    amount: numeric value, or None for "offered but amount unknown".
    period: one of mo|qtr|yr|2yr|3yr|period|None.
    unit:   usd|pct|count|text.
    display: explicit display string; if None, it is derived.
    """
    if display is None:
        display = _format_display(amount, period, unit)
    return {"amount": amount, "period": period, "unit": unit, "display": display}


def _format_display(amount, period, unit):
    if amount is None:
        return "Offered"
    suffix = _PERIOD_DISPLAY.get(period, "")
    if unit == "usd":
        if amount == int(amount):
            return f"${int(amount):,}{suffix}"
        return f"${amount:,.2f}{suffix}"
    if unit == "pct":
        return f"{int(amount) if amount == int(amount) else amount}%{suffix}"
    if unit == "count":
        return f"{amount}{suffix}"
    return str(amount)


# CMS PBP period codes -> our period tokens. Codes vary by sub-section; this is
# the common mapping used across b13b/b16/b17. Unknown codes -> None (no suffix).
_PERIOD_CODE = {
    "1": "mo", "2": "qtr", "3": "yr",
    "5": "mo", "7": "yr",   # alternate code sets seen in b13b
}


def parse_money(raw):
    """'455.00' -> 455 ; '12.50' -> 12.5 ; '' / None / blank -> None."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return None
    return int(val) if val == int(val) else val


def period_code_to_token(code):
    """Map a CMS period code string to our period token, or None."""
    if code is None:
        return None
    return _PERIOD_CODE.get(str(code).strip(), None)


import json
from datetime import datetime


def _load(plan):
    """Return parsed details_json dict (always a dict)."""
    if not plan.details_json:
        return {}
    try:
        return json.loads(plan.details_json)
    except (json.JSONDecodeError, TypeError):
        return {}


def _save(plan, data):
    plan.details_json = json.dumps(data)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def get_field(plan, field):
    """Full provenance record for a field, or None if absent.

    Returns {value, source, trust, as_of, updated_at, updated_by, history}.
    """
    meta = _load(plan).get("_meta", {})
    rec = meta.get(field)
    return rec if rec else None


def field_value(plan, field):
    """Plain structured value for a field (what templates/filters call), or None."""
    rec = get_field(plan, field)
    return rec["value"] if rec else None


def set_human_value(plan, field, value, user, note=None, verify=False):
    """Apply a human edit (agent) or verification (verify=True -> AJ verified).

    Always applies immediately. Records attribution + appends history.
    """
    data = _load(plan)
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value")
    prev_display = prev["display"] if prev else None
    source = "aj_verified" if verify else "agent_edit"
    trust = "human_verified" if verify else "agent_entered"
    history = meta.get(field, {}).get("history", [])
    history.append({
        "at": _now(),
        "by": getattr(user, "name", None),
        "from": prev_display,
        "to": value["display"],
        "note": note,
    })
    meta[field] = {
        "value": value,
        "source": source,
        "trust": trust,
        "as_of": str(plan.year),
        "updated_at": _now(),
        "updated_by": getattr(user, "name", None),
        "history": history,
    }
    _save(plan, data)


_CMS_TRUST = "cms_authoritative"


def _append_history(rec, by, frm, to, note):
    rec.setdefault("history", []).append(
        {"at": _now(), "by": by, "from": frm, "to": to, "note": note}
    )


def set_cms_value(plan, field, value, cms_source):
    """Apply a CMS-sourced value using the precedence rules.

    Returns one of: 'written' | 'refreshed' | 'overwrote_firstlook'
                    | 'promoted_verified' | 'conflict_flagged' | 'skipped_human'.
    Maintains plan.cms_synced_at. Sets plan.has_unresolved_conflicts on conflict.
    """
    data = _load(plan)
    meta = data.setdefault("_meta", {})
    existing = meta.get(field)
    plan.cms_synced_at = datetime.utcnow()

    def _write(trust, source, action, history_note=None, prev_display=None):
        rec = existing or {}
        _append_history(rec, by=None, frm=prev_display,
                        to=value["display"], note=history_note)
        rec.update({
            "value": value, "source": source, "trust": trust,
            "as_of": str(plan.year), "updated_at": _now(),
            "updated_by": None,
        })
        meta[field] = rec
        _save(plan, data)
        return action

    if existing is None:
        # brand new field from CMS
        return _write(_CMS_TRUST, cms_source, "written")

    trust = existing.get("trust")
    prev_display = existing.get("value", {}).get("display")
    _ev = existing.get("value", {})
    same = (
        _ev.get("amount") == value.get("amount")
        and _ev.get("period") == value.get("period")
        and _ev.get("unit") == value.get("unit")
    )

    if trust == "human_verified":
        _save(plan, data)  # persist cms_synced_at bump only
        return "skipped_human"

    if trust == "agent_entered":
        if same:
            # CMS confirms the agent — lock as verified
            existing["trust"] = "human_verified"
            existing["source"] = "aj_verified"
            _append_history(existing, by=None, frm=prev_display,
                            to=value["display"], note="CMS confirmed agent value")
            existing["updated_at"] = _now()
            meta[field] = existing
            _save(plan, data)
            return "promoted_verified"
        # CMS disagrees with agent -> flag, do NOT overwrite
        _flag_conflict(data, plan, field, existing, value, cms_source)
        _save(plan, data)
        plan.has_unresolved_conflicts = True
        return "conflict_flagged"

    if trust == "unverified":  # carrier_first_look
        if same:
            return _write(_CMS_TRUST, cms_source, "refreshed", prev_display=prev_display)
        return _write(_CMS_TRUST, cms_source, "overwrote_firstlook", prev_display=prev_display)

    # prior CMS value -> refresh
    return _write(_CMS_TRUST, cms_source, "refreshed", prev_display=prev_display)


def _flag_conflict(data, plan, field, existing, incoming, cms_source):
    conflicts = data.setdefault("_conflicts", [])
    # Idempotency: don't stack duplicate unresolved conflicts for the same field
    # (sync scripts run repeatedly). One open conflict per field is enough.
    for c in conflicts:
        if c["field"] == field and not c.get("resolved"):
            return
    conflicts.append({
        "field": field,
        "existing": {
            "value": existing["value"]["display"],
            "source": existing.get("source"),
            "by": existing.get("updated_by"),
            "at": existing.get("updated_at"),
        },
        "incoming": {"value": incoming["display"], "source": cms_source, "at": _now()},
        "flagged_at": _now(),
        "resolved": False, "resolved_by": None, "resolved_at": None, "resolution": None,
    })


def list_conflicts(plan, unresolved_only=True):
    conflicts = _load(plan).get("_conflicts", [])
    if unresolved_only:
        return [c for c in conflicts if not c.get("resolved")]
    return conflicts


def resolve_conflict(plan, field, chosen, user, note=None):
    """AJ resolves a conflict by choosing the surviving value (human_verified).

    Marks the conflict resolved, writes the chosen value, recomputes
    plan.has_unresolved_conflicts.
    """
    data = _load(plan)
    # write the chosen value as human-verified
    meta = data.setdefault("_meta", {})
    prev = meta.get(field, {}).get("value", {}).get("display")
    history = meta.get(field, {}).get("history", [])
    history.append({"at": _now(), "by": getattr(user, "name", None),
                    "from": prev, "to": chosen["display"],
                    "note": note or "conflict resolved"})
    meta[field] = {
        "value": chosen, "source": "aj_verified", "trust": "human_verified",
        "as_of": str(plan.year), "updated_at": _now(),
        "updated_by": getattr(user, "name", None), "history": history,
    }
    # mark matching conflicts resolved
    for c in data.get("_conflicts", []):
        if c["field"] == field and not c.get("resolved"):
            c["resolved"] = True
            c["resolved_by"] = getattr(user, "name", None)
            c["resolved_at"] = _now()
            c["resolution"] = chosen["display"]
    _save(plan, data)
    # recompute flag
    remaining = [c for c in data.get("_conflicts", []) if not c.get("resolved")]
    plan.has_unresolved_conflicts = bool(remaining)
