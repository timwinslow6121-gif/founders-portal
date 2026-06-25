"""Data-Integrity Radar — the ONE registry of invariants. Read-only.

An invariant is a named truth that must hold; its function finds every violating row.
The CLI (scripts/audit_integrity.py), the /admin/integrity dashboard, and the CI guard
(tests/test_integrity_guards.py) ALL iterate this registry — add one @invariant and it
appears in all three. NO function here may mutate the DB."""
from dataclasses import dataclass, field


@dataclass
class Violation:
    key: str
    severity: str          # high | med | low
    domain: str            # data | consistency | route
    count: int
    description: str
    sample: list = field(default_factory=list)


REGISTRY = {}              # key -> wrapped callable returning Violation
_META = {}                 # key -> (severity, domain, description)
_SEV_RANK = {"high": 0, "med": 1, "low": 2}


def invariant(key, *, severity, domain, description):
    """Register an invariant. The wrapped fn returns (count, sample); the wrapper
    turns that into a Violation. Keys must be unique."""
    def deco(fn):
        def wrapped():
            count, sample = fn()
            return Violation(key=key, severity=severity, domain=domain,
                             count=count, description=description, sample=sample)
        REGISTRY[key] = wrapped
        _META[key] = (severity, domain, description)
        return wrapped
    return deco


def run_all():
    """Run every registered invariant; return Violations sorted by domain, then
    severity (high first), then key."""
    results = [fn() for fn in REGISTRY.values()]
    results.sort(key=lambda v: (v.domain, _SEV_RANK.get(v.severity, 9), v.key))
    return results
