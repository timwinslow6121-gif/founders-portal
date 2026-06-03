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
