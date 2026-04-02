"""
tests/test_agency_scoping.py

Stub tests for multi-tenant agency scoping (SC-7).
Will be implemented after Plan 07 scoping sweep adds agency_id to all queries.
"""

import pytest


def test_customer_query_scoped_to_agency(app, db_session, customer, agency):
    pytest.skip("requires agency_id on Customer model — implement after Plan 07 scoping sweep")


def test_cross_tenant_query_returns_nothing(app, db_session):
    pytest.skip("requires agency_id on Customer model — implement after Plan 07 scoping sweep")
