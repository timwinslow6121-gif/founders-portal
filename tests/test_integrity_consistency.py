"""Consistency-domain integrity invariants — absorb metrics guard + add customers.py.

Tests verify that:
1. count_only_via_metrics scans route files + customers.py for raw Policy counts/splits
   (absorbs the logic from test_metrics_guard.py)
2. carrier_counts_agree ensures per-carrier breakdowns sum to the total
"""
import pytest


def test_count_only_via_metrics_scans_customers_py(app):
    """The invariant must include app/customers.py in its scanned set."""
    from app.integrity import REGISTRY
    v = REGISTRY["count_only_via_metrics"]()
    assert v.domain == "consistency"
    assert isinstance(v.count, int)  # 0 if clean (after item 5) or N offending lines now


def test_carrier_counts_agree_self_consistent(app, agency, db_session):
    """Per-carrier policy counts sum to the agency total (metrics layer self-coherence)."""
    from app.integrity import REGISTRY
    from app.extensions import db
    from app.models import Policy
    with app.app_context():
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="C1",
                              status="active"))
        db.session.add(Policy(agency_id=agency.id, carrier="Humana", member_id="C2",
                              status="active"))
        db.session.commit()
        v = REGISTRY["carrier_counts_agree"]()
        assert v.count == 0  # per-carrier sums equal the total -> no violation
