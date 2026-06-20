import pytest
from datetime import date
from app.extensions import db
from app.models import Agency, User, Policy, CommissionLineItem, CommissionStatement
from app.metrics import (Scope, policy_count, book_breakdown,
                         commission_totals, upcoming_terms, attribution_coverage)


@pytest.fixture
def seeded(db_session, app):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        brian = User(name="Brian", email="b@x.com", agency_id=ag.id)
        chris = User(name="Chris", email="c@x.com", agency_id=ag.id)
        db.session.add_all([brian, chris]); db.session.flush()
        # 3 UHC for Brian, 1 Humana for Chris, 1 UHC unattributed
        for i in range(3):
            db.session.add(Policy(carrier="UHC", member_id=f"u{i}", status="active",
                                  agent_id=brian.id, agency_id=ag.id, plan_type="MA",
                                  plan_name="NC-0015"))
        db.session.add(Policy(carrier="Humana", member_id="h1", status="active",
                              agent_id=chris.id, agency_id=ag.id, plan_type="MAPD"))
        db.session.add(Policy(carrier="UHC", member_id="u9", status="active",
                              agent_id=None, agent_id_carrier="6515098", agency_id=ag.id,
                              plan_type="MA"))
        st = CommissionStatement(carrier="UHC", period_label="May 2026", agency_id=ag.id,
                                  statement_date=date(2026, 5, 1))
        db.session.add(st); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=ag.id, statement_id=st.id, carrier="UHC",
            period_label="May 2026", source_ref="x::1", agent_id=brian.id,
            raw_amount=100.0, split_rate=0.55, classification="agent_commission"))
        db.session.commit()
        yield ag.id, brian.id, chris.id


def test_policy_count_scopes(seeded, app):
    ag, brian, chris = seeded
    with app.app_context():
        assert policy_count(Scope(agency_id=ag)) == 5
        assert policy_count(Scope(agency_id=ag, agent_id=brian)) == 3
        assert policy_count(Scope(agency_id=ag, carrier="UHC")) == 4


def test_book_breakdown_by_carrier(seeded, app):
    ag, brian, chris = seeded
    with app.app_context():
        bc = {r["key"]: r["count"] for r in book_breakdown(Scope(agency_id=ag))["by_carrier"]}
        assert bc == {"UHC": 4, "Humana": 1}


def test_commission_totals_from_ledger(seeded, app):
    ag, brian, chris = seeded
    with app.app_context():
        t = commission_totals(Scope(agency_id=ag, period="May 2026"))
        assert round(t["agent_payout"], 2) == 55.0
        assert round(t["founders_keep"], 2) == 45.0


def test_attribution_coverage(seeded, app):
    ag, brian, chris = seeded
    with app.app_context():
        cov = attribution_coverage(Scope(agency_id=ag))
        assert cov["total"] == 5 and cov["attributed"] == 4 and cov["pct"] == 80.0
