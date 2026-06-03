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
