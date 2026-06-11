"""
app/commission/rollup.py

Retired-agent commission rollups.

Cyndi Mortimer and Donald Long are no longer active agents. Per AJ, their
**Aetna and UHC** business (only those two carriers — small, but real) rolls up
to Brian Freeman, who is paid on it at his 50% rate. Rolling it up here means
the ledger/recap attribute it to Brian automatically, so AJ no longer hand-
computes or hand-tracks it.

This module is the SINGLE source of truth for that rewrite. It rewrites the
*writing-agent name* before agent-matching / split-lookup, so both the split
RATE (Brian's contract) and the ATTRIBUTION (Brian's recap) come out right in
one place.

The rule is deliberately narrow:
  - only the named retired agents,
  - only the named carriers,
  - everything else passes through unchanged.
"""
# Carrier names this rollup applies to (compared case-insensitively).
_ROLLUP_CARRIERS = {"aetna", "uhc"}

# Normalized retired-agent name  ->  the active agent their business rolls up to.
# Keys are _normalize_name() output ("first last", lowercased), so "Long, Donald",
# "LONG, DONALD" and "Donald Long" all map to the same entry, while "Long, Rebekah"
# (a DIFFERENT, active agent) normalizes to "rebekah long" and is untouched.
_RETIRED_ROLLUPS = {
    "donald long": "Brian Freeman",
    "cyndi mortimer": "Brian Freeman",
}


def apply_rollup(writing_agent_raw, carrier):
    """Return the effective writing-agent name after retired-agent rollup.

    For a retired agent (Cyndi/Don) on a rollup carrier (Aetna/UHC), returns
    'Brian Freeman'. Otherwise returns the original name unchanged (including
    None/empty, which pass straight through)."""
    if not writing_agent_raw:
        return writing_agent_raw
    if (carrier or "").strip().lower() not in _ROLLUP_CARRIERS:
        return writing_agent_raw
    # Lazy import avoids a circular import (routes.py imports this module).
    from app.commission.routes import _normalize_name
    normalized = _normalize_name(writing_agent_raw)
    return _RETIRED_ROLLUPS.get(normalized, writing_agent_raw)
