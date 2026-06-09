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


def _mk_line(db, agency, agent, carrier, cls, ptype, raw, split, name, period="May 2026"):
    from app.models import CommissionLineItem, CommissionStatement
    from datetime import date
    stmt = (CommissionStatement.query
            .filter_by(agency_id=agency.id, carrier=carrier, period_label=period).first())
    if stmt is None:
        stmt = CommissionStatement(agency_id=agency.id, carrier=carrier, agent_id=None,
                                   period_label=period, filename="f.xlsx",
                                   statement_date=date(2026, 5, 1))
        db.session.add(stmt); db.session.flush()
    li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier=carrier,
                            period_label=period, source_ref=f"{carrier}::{name}::{raw}",
                            agent_id=agent.id, member_name=name, raw_amount=raw,
                            split_rate=split, classification=cls, payment_type=ptype)
    db.session.add(li); db.session.flush()
    return li


def test_build_carrier_blocks_reconciles_and_counts(db_session, agency):
    from app.models import User
    from app.extensions import db
    from app.commission.recap import build_carrier_blocks

    agent = User(name="Tim Winslow", email="t@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # Devoted: 1 new (initial-new), 1 renewal, 1 chargeback
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "initial - new", 1000.0, 0.55, "Alice")
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "renewal - monthly", 100.0, 0.55, "Bob")
    _mk_line(db, agency, agent, "Devoted", "chargeback", "initial - not new", -200.0, 0.55, "Cara")
    db.session.flush()

    blocks = build_carrier_blocks(agent.id, agency.id, "May 2026")
    dev = next(b for b in blocks if b.carrier == "Devoted")
    # payout = 1000*.55 + 100*.55 - 200*.55 = 550 + 55 - 110 = 495
    assert round(dev.total_payout, 2) == 495.00
    assert dev.new_members == 1            # only the initial-new agent_commission
    # groups present
    kinds = {g.kind for g in dev.groups}
    assert kinds == {"New enrollments", "Renewals", "Chargebacks"}
    # each line carries raw, split, payout that reconciles
    allrows = [r for g in dev.groups for r in g.rows]
    assert round(sum(r.payout for r in allrows), 2) == round(dev.total_payout, 2)


def test_lost_members_and_uhc_manual(db_session, agency):
    from app.models import User, Policy, AgentRecapPeriod
    from app.extensions import db
    from datetime import date
    from app.commission.recap import lost_members_by_carrier, uhc_manual_block

    agent = User(name="Tim Winslow", email="t2@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # 2 Devoted policies termed in May 2026, 1 active (not counted), 1 termed wrong month
    for i, (status, td) in enumerate([("termed", date(2026,5,10)), ("termed", date(2026,5,20)),
                                      ("active", None), ("termed", date(2026,4,2))]):
        db.session.add(Policy(agency_id=agency.id, carrier="Devoted", member_id=f"D{i}",
                              agent_id=agent.id, status=status, term_date=td))
    db.session.flush()

    lost = lost_members_by_carrier(agent.id, agency.id, "May 2026")
    assert lost.get("Devoted") == 2

    # UHC manual block from AgentRecapPeriod
    p = AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id, period_label="May 2026",
                         uhc_manual_amount=4375.68, uhc_manual_note="AEP true-up incl.")
    db.session.add(p); db.session.flush()
    blk = uhc_manual_block(p)
    assert blk is not None
    assert blk.carrier == "UHC"
    assert blk.total_payout == 4375.68
    assert blk.source == "manual"
    assert blk.note == "AEP true-up incl."

    # No UHC figure → no block
    assert uhc_manual_block(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                             period_label="June 2026")) is None
