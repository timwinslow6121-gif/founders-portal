"""
tests/test_commission_recap.py
R2 agent commission recap: per-carrier new-vs-renewal classification, the recap
assembler, publish workflow, access scoping. SQLite in-memory via conftest.
"""


def test_is_new_enrollment_per_carrier():
    from app.commission.recap import is_new_enrollment as nu

    # Devoted: both "initial - new" and "initial - not new" are new enrollments
    assert nu("Devoted", "agent_commission", "initial - new") is True
    assert nu("Devoted", "agent_commission", "initial - not new") is True
    assert nu("Devoted", "agent_commission", "renewal - monthly") is False
    # Humana transaction codes
    assert nu("Humana", "agent_commission", "arcf") is True
    assert nu("Humana", "agent_commission", "med2") is True
    assert nu("Humana", "agent_commission", "arcm") is False
    # BCBS group types
    assert nu("BCBS", "agent_commission", "fy") is True
    assert nu("BCBS", "agent_commission", "new") is True
    assert nu("BCBS", "agent_commission", "renew") is False
    # Aetna sales events
    assert nu("Aetna", "agent_commission", "pro-rata payment") is True
    assert nu("Aetna", "agent_commission", "renewal") is False
    # Chargebacks / overrides / hra are never "new members"
    assert nu("Devoted", "chargeback", "initial - new") is False
    assert nu("Devoted", "founders_override", "override") is False
    assert nu("Devoted", "hra_bonus", "hra") is False
    # Unknown carrier/type → conservative False
    assert nu("UHC", "agent_commission", "whatever") is False


def test_agent_recap_period_model(db_session, agency):
    from app.models import AgentRecapPeriod, User
    from app.extensions import db

    agent = User(name="Tim Winslow", email="tim@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    p = AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                         period_label="May 2026")
    db.session.add(p); db.session.flush()

    got = AgentRecapPeriod.query.filter_by(agent_id=agent.id,
                                           period_label="May 2026").first()
    assert got.status == "draft"          # default
    assert got.uhc_manual_amount is None
    assert got.prior_year_total is None
    assert got.published_at is None
