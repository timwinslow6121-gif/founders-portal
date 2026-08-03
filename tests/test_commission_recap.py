"""
tests/test_commission_recap.py
R2 agent commission recap: per-carrier new-vs-renewal classification, the recap
assembler, publish workflow, access scoping. SQLite in-memory via conftest.
"""
import pytest


@pytest.fixture
def app_ctx():
    from app import create_app
    from app.extensions import db
    from app.models import Agency
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False)
    with app.app_context():
        db.create_all()
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        yield app, ag.id
        db.session.remove(); db.drop_all()


def test_contract_rate_for_returns_rate_and_none(app_ctx):
    """The rate lookup is the ONE place a contract rate is resolved. It must
    return None -- never a fabricated default -- when no contract exists, so
    the UI can say 'no contract on file' instead of implying 0.55."""
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import contract_rate_for
    app, agency_id = app_ctx

    mike = User(email="mike@x.com", name="Mike Lauzurique",
                agency_id=agency_id, role="agent")
    db.session.add(mike); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=mike.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.525))
    db.session.flush()

    assert contract_rate_for(mike.id, "UHC", agency_id) == 0.525
    # carrier with no contract -> None, NOT 0.55
    assert contract_rate_for(mike.id, "Humana", agency_id) is None
    # no agent at all -> None
    assert contract_rate_for(None, "UHC", agency_id) is None


def test_contract_rate_for_uses_cache(app_ctx):
    """A caller passing a cache must not re-query per row -- the Fidelity view
    serializes ~4k rows and a per-row query would reintroduce the N+1 the
    50a7f4a perf fix removed."""
    from app.extensions import db
    from app.models import User, AgentCarrierContract
    from app.commission.recap import contract_rate_for
    app, agency_id = app_ctx

    u = User(email="a@x.com", name="A Agent", agency_id=agency_id, role="agent")
    db.session.add(u); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=u.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.5))
    db.session.flush()

    cache = {}
    assert contract_rate_for(u.id, "UHC", agency_id, cache) == 0.5
    assert (u.id, "uhc") in cache
    # poison the cache; a cached hit must be returned without re-querying
    cache[(u.id, "uhc")] = 0.99
    assert contract_rate_for(u.id, "UHC", agency_id, cache) == 0.99


def test_fidelity_row_exposes_contract_rate_and_off_contract_flag(app_ctx):
    """The Fidelity table builds its edit form in JS from this row dict, so the
    rate must travel in JSON -- rendering it per row would re-inflate the ~4k-row
    DOM that merge 50a7f4a shrank."""
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, Agency,
                            CommissionStatement, CommissionLineItem)
    from app.commission.recap import fidelity_row
    from datetime import date
    app, agency_id = app_ctx

    mike = User(email="m@x.com", name="Mike Lauzurique",
                agency_id=agency_id, role="agent")
    db.session.add(mike); db.session.flush()
    db.session.add(AgentCarrierContract(agent_id=mike.id, carrier="UHC",
                                        agency_id=agency_id, is_active=True,
                                        split_rate=0.525))
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="July 2026", filename="u.xlsx",
                               statement_date=date(2026, 7, 1))
    db.session.add(stmt); db.session.flush()

    on = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                            carrier="UHC", source_ref="uhc::0::1",
                            agent_id=mike.id, raw_amount=4.59, split_rate=0.525,
                            classification="agent_commission",
                            member_name="ON, CONTRACT")
    off = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                             carrier="UHC", source_ref="uhc::0::2",
                             agent_id=mike.id, raw_amount=4.59, split_rate=1.0,
                             classification="agent_commission",
                             member_name="OFF, CONTRACT")
    db.session.add_all([on, off]); db.session.flush()

    r_on = fidelity_row(on)
    assert r_on["contract_rate"] == 0.525
    assert r_on["off_contract"] is False

    r_off = fidelity_row(off)
    assert r_off["contract_rate"] == 0.525
    assert r_off["off_contract"] is True, "stored 1.0 vs contract 0.525"


def test_fidelity_row_no_contract_is_not_off_contract(app_ctx):
    """No contract on file means we cannot judge the rate -- report None and do
    NOT flag the row, or every unattributed line screams false alarm."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    from app.commission.recap import fidelity_row
    from datetime import date
    app, agency_id = app_ctx

    u = User(email="n@x.com", name="No Contract", agency_id=agency_id, role="agent")
    db.session.add(u); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="July 2026", filename="u.xlsx",
                               statement_date=date(2026, 7, 1))
    db.session.add(stmt); db.session.flush()
    li = CommissionLineItem(agency_id=agency_id, statement_id=stmt.id,
                            carrier="UHC", source_ref="uhc::0::3",
                            agent_id=u.id, raw_amount=10.0, split_rate=1.0,
                            classification="agent_commission",
                            member_name="NO, CONTRACT")
    db.session.add(li); db.session.flush()

    r = fidelity_row(li)
    assert r["contract_rate"] is None
    assert r["off_contract"] is False


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
    # Healthspring: key MUST match the ledger's exact carrier literal ("Healthspring",
    # lowercase s). Regression guard for the HealthSpring/Healthspring mismatch.
    assert nu("Healthspring", "agent_commission", "initial") is True
    assert nu("Healthspring", "agent_commission", "initial - new") is True


def test_new_payment_type_keys_match_ledger_carrier_literals():
    """Every _NEW_PAYMENT_TYPES key must be a real carrier literal the ledger
    extractors actually emit — else is_new_enrollment silently never matches."""
    from app.commission.recap import _NEW_PAYMENT_TYPES
    from app.commission.ledger import EXTRACTORS
    ledger_carriers = set(EXTRACTORS.keys())   # exact literals used on CommissionLineItem.carrier
    for key in _NEW_PAYMENT_TYPES:
        assert key in ledger_carriers, f"{key!r} not a ledger carrier literal {ledger_carriers}"


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


def test_hra_bonus_is_included_in_agent_payout(db_session, agency):
    """HRA bonuses ARE agent commission (they split to the agent). The recap must
    count them in total_payout — they were wrongly excluded, making each agent's
    Devoted total short by the HRA amount (the live $50 Brian discrepancy)."""
    from app.models import User
    from app.extensions import db
    from app.commission.recap import build_carrier_blocks

    agent = User(name="Tim Winslow", email="hra@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # Devoted: 1 renewal $100 + 1 HRA bonus $50, both split 0.50
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "renewal - monthly", 100.0, 0.50, "Bob")
    _mk_line(db, agency, agent, "Devoted", "hra_bonus", "hra", 50.0, 0.50, "Bob")
    db.session.flush()

    blocks = build_carrier_blocks(agent.id, agency.id, "May 2026")
    dev = next(b for b in blocks if b.carrier == "Devoted")
    # payout = 100*.50 (renewal) + 50*.50 (HRA) = 50 + 25 = 75
    assert round(dev.total_payout, 2) == 75.00
    # HRA shows in its own "HRA" group, NOT counted as a new member
    assert dev.new_members == 0
    kinds = {g.kind for g in dev.groups}
    assert "HRA" in kinds
    # drill-down still reconciles to the total exactly
    allrows = [r for g in dev.groups for r in g.rows]
    assert round(sum(r.payout for r in allrows), 2) == round(dev.total_payout, 2)


def test_commission_adjustment_flows_into_carrier_block(db_session, agency):
    """A CommissionAdjustment (agent+carrier+period) shows as its own line in that
    carrier block and is added to the carrier total — AJ's reconciliation line."""
    from app.models import User, CommissionAdjustment
    from app.extensions import db
    from app.commission.recap import build_carrier_blocks

    agent = User(name="Tim Winslow", email="adj@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # UHC: $100 renewal payout @0.55 = 55.00
    _mk_line(db, agency, agent, "UHC", "agent_commission", "renewal", 100.0, 0.55, "Member A")
    # AJ corrects a prior overpayment: -$20
    db.session.add(CommissionAdjustment(agency_id=agency.id, agent_id=agent.id,
                   carrier="UHC", period_label="May 2026", amount=-20.0,
                   note="April overpayment correction"))
    db.session.flush()

    blocks = build_carrier_blocks(agent.id, agency.id, "May 2026")
    uhc = next(b for b in blocks if b.carrier == "UHC")
    # total = 55.00 renewal - 20.00 adjustment = 35.00
    assert round(uhc.total_payout, 2) == 35.00
    # adjustment is its own group + line carrying the note
    adj = next(g for g in uhc.groups if g.kind == "Adjustments")
    assert round(adj.subtotal, 2) == -20.00
    assert adj.rows[0].member_name == "April overpayment correction"
    # not counted as a member
    assert uhc.new_members == 0
    # drill-down still reconciles to the total
    allrows = [r for g in uhc.groups for r in g.rows]
    assert round(sum(r.payout for r in allrows), 2) == round(uhc.total_payout, 2)


def test_admin_can_add_and_delete_adjustment(db_session, app, client, agency):
    """End-to-end: AJ posts an adjustment, it persists; deleting removes it."""
    from app.extensions import db
    from app.models import User, CommissionAdjustment

    with app.app_context():
        admin = User(name="AJ", email="ajadmin@x.com", is_admin=True, agency_id=agency.id)
        agent = User(name="Tim Winslow", email="timadj@x.com", agency_id=agency.id)
        db.session.add_all([admin, agent]); db.session.commit()
        aid, uid = agent.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)

    resp = client.post("/admin/commissions/recap/adjustment", data={
        "agent_id": aid, "period": "May 2026", "carrier": "UHC",
        "amount": "-120.00", "note": "April overpayment correction"}, follow_redirects=False)
    assert resp.status_code in (302, 303)

    with app.app_context():
        adj = CommissionAdjustment.query.filter_by(agent_id=aid, carrier="UHC").first()
        assert adj is not None and adj.amount == -120.0
        assert adj.note == "April overpayment correction"
        adj_id = adj.id

    resp = client.post(f"/admin/commissions/recap/adjustment/{adj_id}/delete")
    assert resp.status_code in (302, 303)
    with app.app_context():
        assert CommissionAdjustment.query.filter_by(agent_id=aid).count() == 0


def test_admin_recap_page_renders_with_adjustment(db_session, app, client, agency):
    """The admin recap template renders (form + existing adjustment row) without a
    Jinja error — guards the template wiring for #4."""
    from app.extensions import db
    from app.models import User, CommissionAdjustment

    with app.app_context():
        admin = User(name="AJ", email="ajr@x.com", is_admin=True, agency_id=agency.id)
        agent = User(name="Tim Winslow", email="timr@x.com", agency_id=agency.id)
        db.session.add_all([admin, agent]); db.session.flush()
        _mk_line(db, agency, agent, "UHC", "agent_commission", "renewal", 100.0, 0.55, "Member A")
        db.session.add(CommissionAdjustment(agency_id=agency.id, agent_id=agent.id,
                       carrier="UHC", period_label="May 2026", amount=-20.0,
                       note="April overpayment correction"))
        db.session.commit()
        aid, uid = agent.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get(f"/admin/commissions/recap?agent_id={aid}&period=May%202026")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Add adjustment" in body                  # the form
    assert "April overpayment correction" in body    # the existing adjustment in the admin list
    # carrier total reflects the adjustment server-side: 100*.55 - 20 = 35.00
    assert "35.00" in body
    # the "Adjustments" group + line come through the drill-down JSON endpoint
    j = client.get(f"/commissions/recap/carrier?agent_id={aid}&period=May%202026&carrier=UHC")
    assert j.status_code == 200
    data = j.get_json()
    kinds = {g["kind"] for g in data["groups"]}
    assert "Adjustments" in kinds


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


def test_medico_and_wellable_collapse_to_one_wellabe_container(db_session, agency):
    """Medico is the parent company of Wellabe; we're contracted as Wellabe. The
    dashboard must show ONE "Wellabe" container — never a separate "Medico" or the
    misspelled "Wellable" — whether the contract/data is under either name."""
    from app.models import User, AgentCarrierContract
    from app.extensions import db
    from app.commission.recap import build_recap, canon_carrier

    assert canon_carrier("Medico") == "Wellabe"
    assert canon_carrier("Wellable") == "Wellabe"
    assert canon_carrier("Wellabe") == "Wellabe"
    assert canon_carrier("Aetna") == "Aetna"

    agent = User(name="Tim Winslow", email="tw@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()
    # Tim's real case: BOTH a Medico and a Wellable contract + one Medico data row
    for c in ("Medico", "Wellable"):
        db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=agent.id,
                                            carrier=c, split_rate=0.55, is_active=True))
    _mk_line(db, agency, agent, "Medico", "agent_commission", "new", 100.0, 0.55, "Ann")
    db.session.flush()

    r = build_recap(agent.id, agency.id, "May 2026")
    names = [b.carrier for b in r.carriers]
    assert "Medico" not in names
    assert "Wellable" not in names
    assert names.count("Wellabe") == 1        # exactly ONE, merged
    wellabe = next(b for b in r.carriers if b.carrier == "Wellabe")
    assert round(wellabe.total_payout, 2) == 55.00   # the Medico data landed under Wellabe


def test_build_recap_headline_and_ytd(db_session, agency):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    from app.commission.recap import build_recap

    agent = User(name="Tim Winslow", email="t3@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()

    # May: Devoted 1 new $1000 + 1 chargeback -$200 (payouts 550, -110) ; net 440
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "initial - new", 1000.0, 0.55, "A")
    _mk_line(db, agency, agent, "Devoted", "chargeback", "initial - not new", -200.0, 0.55, "B")
    # AJ entered UHC $2000
    db.session.add(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                    period_label="May 2026", uhc_manual_amount=2000.0))
    db.session.flush()

    r = build_recap(agent.id, agency.id, "May 2026")
    # GROSS = before chargebacks: Devoted new 550 + UHC manual 2000 = 2550
    assert round(r.total_paid, 2) == 2550.00
    # NET after chargebacks: gross 2550 - 110 chargeback = 2440
    assert round(r.net_after_chargebacks, 2) == 2440.00
    # they MUST differ when chargebacks exist
    assert r.total_paid != r.net_after_chargebacks
    assert r.new_members == 1
    # carriers include both Devoted (ledger) and UHC (manual)
    names = {b.carrier for b in r.carriers}
    assert "Devoted" in names and "UHC" in names
    uhc = next(b for b in r.carriers if b.carrier == "UHC")
    assert uhc.source == "manual"
    # pct_of_book sums to ~100 across carriers with members (UHC has 0 members here)
    # run-rate is a positive projection from YTD
    assert r.run_rate >= r.ytd_current


def test_send_email_builds_brevo_payload(monkeypatch, app):
    from app import mailer
    captured = {}

    class FakeResp:
        status_code = 201
        text = ""

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url; captured["json"] = json; captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(mailer, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    with app.app_context():
        app.config["BREVO_API_KEY"] = "k"
        app.config["MAIL_FROM"] = "from@x.com"
        ok = mailer.send_email("to@x.com", "Subj", "hello body")
    assert ok is True
    assert captured["url"].endswith("/v3/smtp/email")
    assert captured["headers"]["api-key"] == "k"
    assert captured["json"]["sender"]["email"] == "from@x.com"
    assert captured["json"]["to"] == [{"email": "to@x.com"}]
    assert captured["json"]["subject"] == "Subj"
    assert captured["json"]["textContent"] == "hello body"


def test_send_email_with_attachment(monkeypatch, app):
    import base64
    from app import mailer
    captured = {}

    class FakeResp:
        status_code = 202; text = ""

    monkeypatch.setattr(mailer, "requests",
                        type("R", (), {"post": staticmethod(lambda url, json=None, headers=None, timeout=None: (captured.update(json=json) or FakeResp()))}))
    with app.app_context():
        app.config["BREVO_API_KEY"] = "k"; app.config["MAIL_FROM"] = "from@x.com"
        ok = mailer.send_email("to@x.com", "S", "b",
                               attachment={"content": b"PDFBYTES", "name": "labels.pdf"})
    assert ok is True
    att = captured["json"]["attachment"][0]
    assert att["name"] == "labels.pdf"
    assert base64.b64decode(att["content"]) == b"PDFBYTES"


def test_send_email_no_key_returns_false(app):
    from app import mailer
    with app.app_context():
        app.config["BREVO_API_KEY"] = ""
        app.config["MAIL_FROM"] = "from@x.com"
        assert mailer.send_email("to@x.com", "S", "b") is False


def test_publish_workflow_and_visibility(db_session, agency, app, monkeypatch):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    from app.commission import recap as R

    agent = User(name="Tim", email="pub@x.com", agency_id=agency.id)
    admin = User(name="AJ", email="aj@x.com", agency_id=agency.id, is_admin=True)
    db.session.add_all([agent, admin]); db.session.flush()

    # draft created on demand, not visible to agent
    p = R.get_or_create_period(agent.id, agency.id, "May 2026")
    assert p.status == "draft"
    assert R.is_visible_to_agent(p) is False

    # publish notifies once
    calls = []
    monkeypatch.setattr(R, "send_email", lambda *a, **k: calls.append(a) or True)
    with app.app_context():
        R.publish_recap(p, published_by_id=admin.id, agent_email=agent.email,
                        total_paid=2440.0, base_url="http://x")
    db.session.flush()
    assert p.status == "published"
    assert p.published_at is not None
    assert p.notified_at is not None
    assert R.is_visible_to_agent(p) is True
    assert len(calls) == 1

    # re-publish does not re-notify
    R.publish_recap(p, published_by_id=admin.id, agent_email=agent.email,
                    total_paid=2440.0, base_url="http://x")
    assert len(calls) == 1


def _login(client, app, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)


def test_agent_recap_route_hides_draft_shows_published(client, app, agency, db_session):
    from app.models import User, AgentRecapPeriod
    from app.extensions import db
    agent = User(name="Tim", email="route@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()
    _mk_line(db, agency, agent, "Devoted", "agent_commission", "renewal - monthly", 100.0, 0.55, "A")
    db.session.add(AgentRecapPeriod(agency_id=agency.id, agent_id=agent.id,
                                    period_label="May 2026", status="draft"))
    db.session.commit()
    agent_id = agent.id

    _login(client, app, agent_id)
    # draft → agent sees a "pending" state, not the numbers
    resp = client.get("/commissions/recap?period=May+2026")
    assert resp.status_code == 200
    assert b"pending" in resp.data.lower() or b"not yet" in resp.data.lower()

    # publish, then the total shows
    with app.app_context():
        p = AgentRecapPeriod.query.filter_by(agent_id=agent_id, period_label="May 2026").first()
        p.status = "published"
        db.session.commit()
    resp2 = client.get("/commissions/recap?period=May+2026")
    assert b"55" in resp2.data  # $55.00 payout appears


def test_latest_period_with_data_uses_statement_date_chronology(db_session, agency):
    """Admin default = most recent period that has commission data, ordered by the
    real statement_date (NOT alphabetical period_label). None when no data."""
    from app.models import CommissionStatement
    from app.extensions import db
    from datetime import date
    from app.commission.recap import latest_period_with_data

    assert latest_period_with_data(agency.id) is None   # no data yet

    # April uploaded after May chronologically? No — use statement_date as truth.
    db.session.add(CommissionStatement(agency_id=agency.id, carrier="Devoted", agent_id=None,
                                       period_label="April 2026", filename="a",
                                       statement_date=date(2026, 4, 1)))
    db.session.add(CommissionStatement(agency_id=agency.id, carrier="Humana", agent_id=None,
                                       period_label="May 2026", filename="m",
                                       statement_date=date(2026, 5, 1)))
    db.session.flush()
    # May has the later statement_date → it's the default, even though "April" < "May"
    # alphabetically would also work here, but Dec<Feb etc. would break alphabetical.
    assert latest_period_with_data(agency.id) == "May 2026"


def test_carrier_block_rows_reconcile_to_total_exactly(db_session, agency):
    """Fix #4: drill-down rows MUST sum to the carrier total to the penny — no
    per-row vs per-total rounding drift (the $431.01 vs $430.99 bug). Uses amounts
    whose raw×split has sub-cent tails that would drift if rounded inconsistently."""
    from app.models import User
    from app.extensions import db
    from app.commission.recap import build_carrier_blocks
    agent = User(name="Justin Basinger", email="recon@x.com", agency_id=agency.id)
    db.session.add(agent); db.session.flush()
    # 100.05 * 0.525 = 52.52625 → row rounds to 52.53. Three of them:
    #   OLD (sum-then-round): round(157.57875, 2) = 157.58  ← total
    #   rows shown (each 52.53) sum to 157.59               ← MISMATCH (the bug)
    #   NEW (round-then-sum): total = 157.59 = rows         ← reconciles
    for i in range(3):
        _mk_line(db, agency, agent, "BCBS", "agent_commission", "renew", 100.05, 0.525, f"M{i}")
    db.session.flush()
    blocks = build_carrier_blocks(agent.id, agency.id, "May 2026")
    b = next(x for x in blocks if x.carrier == "BCBS")
    all_rows = [r for g in b.groups for r in g.rows]
    assert all(round(r.payout, 2) == r.payout for r in all_rows)   # every row 2dp
    assert all_rows[0].payout == 52.53
    # rows sum EXACTLY to the carrier total (the reconciliation guarantee)
    assert round(sum(r.payout for r in all_rows), 2) == b.total_payout
    assert b.total_payout == 157.59      # reconciled value, NOT the old drifted 157.58
    # and to the sum of group subtotals
    assert round(sum(g.subtotal for g in b.groups), 2) == b.total_payout


# ── #6 admin aggregate matrix (agents × carriers) ────────────────────────

def test_build_aggregate_matrix_payout_keep_and_totals(db_session, agency):
    """The admin matrix: one cell per (agent, carrier) with payout + founders-keep,
    plus row/column/grand totals. Cell payout matches the agent's recap carrier
    block; keep includes founders_override; adjustments fold into payout."""
    from app.models import User, CommissionAdjustment
    from app.extensions import db
    from app.commission.recap import build_aggregate_matrix

    tim = User(name="Tim Winslow", email="mx-tim@x.com", agency_id=agency.id)
    reb = User(name="Rebekah Long", email="mx-reb@x.com", agency_id=agency.id)
    db.session.add_all([tim, reb]); db.session.flush()

    # Tim UHC: renewal $100@.55 (payout 55, keep 45) + a founders_override $4.59 (keep 4.59)
    _mk_line(db, agency, tim, "UHC", "agent_commission", "renewal", 100.0, 0.55, "A")
    _mk_line(db, agency, tim, "UHC", "founders_override", "override", 4.59, None, "A")
    # Tim Devoted: hra_bonus $50@.50 (payout 25, keep 25)
    _mk_line(db, agency, tim, "Devoted", "hra_bonus", "hra", 50.0, 0.50, "B")
    # Rebekah UHC: renewal $200@.55 (payout 110, keep 90)
    _mk_line(db, agency, reb, "UHC", "agent_commission", "renewal", 200.0, 0.55, "C")
    # Tim UHC: a quarantined "New" enrollment $500 (split_rate None) — must NOT be
    # counted as Founders keep; it's pending review.
    _mk_line(db, agency, tim, "UHC", "needs_manual_review", "New", 500.0, None, "D")
    # Tim UHC adjustment -$20
    db.session.add(CommissionAdjustment(agency_id=agency.id, agent_id=tim.id,
                   carrier="UHC", period_label="May 2026", amount=-20.0, note="corr"))
    db.session.flush()

    m = build_aggregate_matrix(agency.id, scope="month", period_label="May 2026")

    carriers = m["carriers"]
    assert "UHC" in carriers and "Devoted" in carriers
    cell = {(r["agent_name"], c): r["cells"].get(c) for r in m["rows"] for c in carriers}

    # Tim UHC payout = 55 - 20 adjustment = 35.
    # keep splits into Founders' split-share (45 from the renewal) + override (4.59).
    tim_uhc = cell[("Tim Winslow", "UHC")]
    assert round(tim_uhc["payout"], 2) == 35.00
    assert round(tim_uhc["split_keep"], 2) == 45.00       # Founders' share of the split
    assert round(tim_uhc["override"], 2) == 4.59          # pure override lines
    # keep = split + override ONLY — the $500 quarantine row is NOT in keep
    assert round(tim_uhc["keep"], 2) == 49.59
    assert round(tim_uhc["pending"], 2) == 500.00         # surfaced separately
    # Rebekah UHC payout 110
    assert round(cell[("Rebekah Long", "UHC")]["payout"], 2) == 110.00
    # column total UHC payout = 35 + 110 = 145
    assert round(m["carrier_totals"]["UHC"]["payout"], 2) == 145.00
    # Tim row total payout = 35 (UHC) + 25 (Devoted HRA) = 60
    tim_row = next(r for r in m["rows"] if r["agent_name"] == "Tim Winslow")
    assert round(tim_row["payout_total"], 2) == 60.00
    # grand total payout = 60 + 110 = 170
    assert round(m["grand"]["payout"], 2) == 170.00


def test_admin_aggregate_page_renders(db_session, app, client, agency):
    """The All-Commissions matrix renders end-to-end (route + template)."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        admin = User(name="AJ", email="agg-admin@x.com", is_admin=True, agency_id=agency.id)
        tim = User(name="Tim Winslow", email="agg-tim@x.com", agency_id=agency.id)
        db.session.add_all([admin, tim]); db.session.flush()
        _mk_line(db, agency, tim, "UHC", "agent_commission", "renewal", 100.0, 0.55, "A")
        db.session.commit()
        uid = admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get("/admin/commissions/aggregate?scope=month&period=May%202026")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "All Commissions" in body
    assert "Tim Winslow" in body
    assert "Year-to-date" in body          # the toggle
    # ytd scope also renders
    assert client.get("/admin/commissions/aggregate?scope=ytd").status_code == 200
    # (admin guard is the same `if not current_user.is_admin: abort(403)` as
    # admin_recap/audit — covered there; not re-tested here.)


def test_admin_aggregate_blocks_non_admin(app, db_session, agency):
    """Non-admin gets 403 (fresh client, single login — like the audit guard test)."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        na = User(name="Agent X", email="agg-block@x.com", is_admin=False, agency_id=agency.id)
        db.session.add(na); db.session.commit()
        na_id = na.id
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(na_id)
    assert c.get("/admin/commissions/aggregate").status_code == 403


# ── #4 carrier-period status (received / confirmed_zero / pending) ────────

def test_carrier_period_status(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionStatement, CarrierPeriodConfirmation
    from app.commission.recap import carrier_period_status
    from datetime import date

    with app.app_context():
        # BCBS uploaded for May -> received
        db.session.add(CommissionStatement(agency_id=agency.id, carrier="BCBS", agent_id=None,
                       period_label="May 2026", filename="b.xlsx", statement_date=date(2026,5,1)))
        # Aetna: no statement, but AJ confirmed $0 -> confirmed_zero
        db.session.add(CarrierPeriodConfirmation(agency_id=agency.id, carrier="Aetna",
                       period_label="May 2026", note="no Aetna business"))
        db.session.commit()

        st = carrier_period_status(agency.id, "May 2026")
        assert st["BCBS"] == "received"
        assert st["Aetna"] == "confirmed_zero"
        # UHC: neither -> pending
        assert st.get("UHC", "pending") == "pending"
        assert carrier_period_status(agency.id, "May 2026", "UHC") == "pending"


def test_recap_shows_contracted_carriers_at_zero_with_status(db_session, app, agency):
    """An agent's recap shows EVERY carrier they're contracted with, even at $0,
    tagged with the period's data status (received / confirmed_zero / pending)."""
    from app.extensions import db
    from app.models import (User, AgentCarrierContract, CommissionStatement,
                            CarrierPeriodConfirmation)
    from app.commission.recap import build_recap
    from datetime import date

    with app.app_context():
        agent = User(name="Tim Winslow", email="contracted@x.com", agency_id=agency.id)
        db.session.add(agent); db.session.flush()
        # contracted with UHC, Aetna, BCBS
        for c in ("UHC", "Aetna", "BCBS"):
            db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=agent.id,
                           carrier=c, is_active=True, split_rate=0.55))
        # UHC has actual business; BCBS statement uploaded (but $0 for Tim);
        # Aetna no statement but AJ confirmed $0.
        _mk_line(db, agency, agent, "UHC", "agent_commission", "renewal", 100.0, 0.55, "A")
        db.session.add(CommissionStatement(agency_id=agency.id, carrier="BCBS", agent_id=None,
                       period_label="May 2026", filename="b.xlsx", statement_date=date(2026,5,1)))
        db.session.add(CarrierPeriodConfirmation(agency_id=agency.id, carrier="Aetna",
                       period_label="May 2026"))
        db.session.commit()

        recap = build_recap(agent.id, agency.id, "May 2026")
        by_carrier = {b.carrier: b for b in recap.carriers}
        assert set(by_carrier) >= {"UHC", "Aetna", "BCBS"}        # all contracted shown
        assert round(by_carrier["UHC"].total_payout, 2) == 55.00
        assert by_carrier["UHC"].status == "received"
        assert by_carrier["BCBS"].total_payout == 0.0
        assert by_carrier["BCBS"].status == "received"            # statement uploaded
        assert by_carrier["Aetna"].total_payout == 0.0
        assert by_carrier["Aetna"].status == "confirmed_zero"     # AJ confirmed no business


def test_aggregate_matrix_has_founders_agency_override_row(db_session, agency):
    """A read-only 'Founders Agency' row sums founders_override per carrier (the
    agency's own override earnings)."""
    from app.models import User
    from app.extensions import db
    from app.commission.recap import build_aggregate_matrix

    tim = User(name="Tim Winslow", email="ag1@x.com", agency_id=agency.id)
    db.session.add(tim); db.session.flush()
    # Tim UHC: renewal (agent) + a $4.59 override (agency)
    _mk_line(db, agency, tim, "UHC", "agent_commission", "renewal", 100.0, 0.55, "A")
    _mk_line(db, agency, tim, "UHC", "founders_override", "override", 4.59, None, "A")
    _mk_line(db, agency, tim, "Devoted", "founders_override", "override", 10.00, None, "B")
    db.session.flush()

    m = build_aggregate_matrix(agency.id, scope="month", period_label="May 2026")
    ar = m["agency_row"]
    assert round(ar["cells"]["UHC"], 2) == 4.59
    assert round(ar["cells"]["Devoted"], 2) == 10.00
    assert round(ar["total"], 2) == 14.59


def test_admin_recap_no_agent_redirects_to_matrix(app, db_session, agency):
    """Admin hitting the recap area with no agent_id lands on the All-Commissions
    matrix, not AJ's own empty 'My Commission' shell."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(name="AJ", email="recapredir@x.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin); db.session.commit()
        uid = admin.id
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    r = c.get("/admin/commissions/recap")   # no agent_id
    assert r.status_code == 302
    assert "/admin/commissions/aggregate" in r.headers["Location"]
    # WITH an agent_id it renders the recap (200)
    r2 = c.get(f"/admin/commissions/recap?agent_id={uid}")
    assert r2.status_code == 200


def test_unassigned_customers_view_and_set_agent(app, db_session, agency):
    """Admin Unassigned view lists no-agent customers with a suggested agent; the
    set-agent endpoint assigns them."""
    from app.extensions import db
    from app.models import User, Customer, CommissionLineItem
    from datetime import date
    with app.app_context():
        admin = User(name="AJ", email="ua-admin@x.com", is_admin=True, agency_id=agency.id)
        reb = User(name="Rebekah Long", email="ua-reb@x.com", agency_id=agency.id)
        db.session.add_all([admin, reb]); db.session.flush()
        c = Customer(agency_id=agency.id, first_name="Ricky", last_name="Sweatt",
                     full_name="SWEATT, RICKY", mbi="8NP5GM6TK40",
                     stub=True, source="commission_import", primary_agent_id=None)
        db.session.add(c); db.session.flush()
        # a UHC line item resolved to Rebekah → the suggestion basis
        from app.models import CommissionStatement
        st = CommissionStatement(agency_id=agency.id, carrier="UHC", agent_id=None,
                                 period_label="May 2026", filename="u.xlsx", statement_date=date(2026,5,1))
        db.session.add(st); db.session.flush()
        db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=st.id, carrier="UHC",
                       period_label="May 2026", source_ref="uhc::0::1", agent_id=reb.id,
                       member_name="SWEATT, RICKY", mbi="8NP5GM6TK40", raw_amount=28.92,
                       classification="agent_commission"))
        db.session.commit()
        cid, uid, rid = c.id, admin.id, reb.id

    cli = app.test_client()
    with cli.session_transaction() as s:
        s["_user_id"] = str(uid)
    r = cli.get("/customers/unassigned")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Ricky Sweatt" in body and "Rebekah Long" in body   # suggested

    # assign
    r2 = cli.post(f"/customers/{cid}/set-agent", data={"agent_id": rid})
    assert r2.status_code in (302, 303)
    with app.app_context():
        from app.models import Customer
        assert Customer.query.get(cid).primary_agent_id == rid


def test_retired_agent_breakdown_separates_cyndis_book_from_brians(app_ctx):
    """The point of writing_agent_raw: Cyndi's rolled-up business pays Brian, and
    this report is what tells them apart. Money is DERIVED from split_breakdown,
    so the figures reconcile to Brian's recap rather than being recomputed."""
    from app.extensions import db
    from app.models import (User, CommissionStatement, CommissionLineItem)
    from app.commission.recap import retired_agent_breakdown
    from datetime import date
    app, agency_id = app_ctx

    brian = User(email="b@x.com", name="Brian Freeman",
                 agency_id=agency_id, role="agent")
    db.session.add(brian); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="May 2026", filename="u.xlsx",
                               statement_date=date(2026, 5, 1))
    db.session.add(stmt); db.session.flush()

    def row(ref, amt, writer):
        return CommissionLineItem(
            agency_id=agency_id, statement_id=stmt.id, carrier="UHC",
            period_label="May 2026", source_ref=ref, agent_id=brian.id,
            raw_amount=amt, split_rate=0.5, classification="agent_commission",
            member_name="M", writing_agent_raw=writer)

    db.session.add_all([
        row("uhc::0::1", 100.0, "MORTIMER, CYNTHIA WALKUP"),
        row("uhc::0::2", 50.0, "MORTIMER, CYNTHIA WALKUP"),
        row("uhc::0::3", 40.0, "LONG, DONALD"),
        row("uhc::0::4", 999.0, "FREEMAN, BRIAN LEE"),   # Brian's OWN — excluded
        row("uhc::0::5", 20.0, None),                     # pre-040 row — excluded
    ])
    db.session.flush()

    out = retired_agent_breakdown(agency_id)
    writers = {g["writing_agent"]: g for g in out}
    assert set(writers) == {"MORTIMER, CYNTHIA WALKUP", "LONG, DONALD"}, \
        "Brian's own rows and NULL-provenance rows must not appear"

    cyndi = writers["MORTIMER, CYNTHIA WALKUP"]
    assert cyndi["rolled_to"] == "Brian Freeman"
    assert cyndi["n_rows"] == 2
    assert cyndi["raw_total"] == 150.0
    assert cyndi["agent_payout"] == 75.0      # 150 * 0.5, derived not recomputed
    assert cyndi["founders_keep"] == 75.0
    # biggest payout first
    assert out[0]["writing_agent"] == "MORTIMER, CYNTHIA WALKUP"


def test_retired_agent_breakdown_filters_by_period(app_ctx):
    """A period filter must not leak other periods into the totals."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    from app.commission.recap import retired_agent_breakdown
    from datetime import date
    app, agency_id = app_ctx

    brian = User(email="b2@x.com", name="Brian Freeman",
                 agency_id=agency_id, role="agent")
    db.session.add(brian); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="May 2026", filename="u.xlsx",
                               statement_date=date(2026, 5, 1))
    db.session.add(stmt); db.session.flush()
    for ref, per in (("uhc::0::1", "May 2026"), ("uhc::0::2", "June 2026")):
        db.session.add(CommissionLineItem(
            agency_id=agency_id, statement_id=stmt.id, carrier="UHC",
            period_label=per, source_ref=ref, agent_id=brian.id,
            raw_amount=100.0, split_rate=0.5, classification="agent_commission",
            member_name="M", writing_agent_raw="LONG, DONALD"))
    db.session.flush()

    may = retired_agent_breakdown(agency_id, period_label="May 2026")
    assert len(may) == 1 and may[0]["raw_total"] == 100.0
    assert len(retired_agent_breakdown(agency_id)) == 2   # unfiltered sees both


def test_retired_agent_breakdown_counts_the_ovr_sibling(app_ctx):
    """A resolved/edited row splits into parent + ::ovr sibling. Both must carry
    the writer, or the report UNDER-states the book: a $100 Cyndi row resolved to
    $60 agent + $40 override would otherwise read as $100 -> $60 raw / $0 kept."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    from app.commission.recap import retired_agent_breakdown
    from app.commission.ledger import resolve_quarantine_line
    from datetime import date
    app, agency_id = app_ctx

    brian = User(email="b3@x.com", name="Brian Freeman",
                 agency_id=agency_id, role="agent")
    db.session.add(brian); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="May 2026", filename="u.xlsx",
                               statement_date=date(2026, 5, 1))
    db.session.add(stmt); db.session.flush()
    li = CommissionLineItem(
        agency_id=agency_id, statement_id=stmt.id, carrier="UHC",
        period_label="May 2026", source_ref="uhc::0::1", agent_id=brian.id,
        raw_amount=100.0, split_rate=None, classification="needs_manual_review",
        member_name="M", writing_agent_raw="MORTIMER, CYNTHIA WALKUP")
    db.session.add(li); db.session.flush()

    # AJ resolves it: $40 to Founders, the $60 remainder splits at 0.5
    resolve_quarantine_line(li, brian.id, 40.0, 0.5)
    db.session.flush()

    sib = CommissionLineItem.query.filter_by(source_ref="uhc::0::1::ovr").first()
    assert sib is not None
    assert sib.writing_agent_raw == "MORTIMER, CYNTHIA WALKUP", \
        "the override sibling must inherit the parent's writer"

    out = retired_agent_breakdown(agency_id)
    assert len(out) == 1
    g = out[0]
    assert g["raw_total"] == 100.0        # 60 parent + 40 sibling, the FULL amount
    assert g["agent_payout"] == 30.0      # 60 * 0.5
    assert g["founders_keep"] == 70.0     # 30 remainder + 40 override


def test_retired_agent_breakdown_sorts_by_signed_payout_not_magnitude(app_ctx):
    """A big chargeback must NOT lead the report — the first row is read as the
    largest contributor, so sorting on abs() actively misleads."""
    from app.extensions import db
    from app.models import User, CommissionStatement, CommissionLineItem
    from app.commission.recap import retired_agent_breakdown
    from datetime import date
    app, agency_id = app_ctx

    brian = User(email="b4@x.com", name="Brian Freeman",
                 agency_id=agency_id, role="agent")
    db.session.add(brian); db.session.flush()
    stmt = CommissionStatement(agency_id=agency_id, carrier="UHC",
                               period_label="May 2026", filename="u.xlsx",
                               statement_date=date(2026, 5, 1))
    db.session.add(stmt); db.session.flush()
    db.session.add_all([
        CommissionLineItem(agency_id=agency_id, statement_id=stmt.id, carrier="UHC",
                           period_label="May 2026", source_ref="uhc::0::1",
                           agent_id=brian.id, raw_amount=-500.0, split_rate=0.5,
                           classification="chargeback", member_name="M",
                           writing_agent_raw="MORTIMER, CYNDI"),
        CommissionLineItem(agency_id=agency_id, statement_id=stmt.id, carrier="UHC",
                           period_label="May 2026", source_ref="uhc::0::2",
                           agent_id=brian.id, raw_amount=120.0, split_rate=0.5,
                           classification="agent_commission", member_name="M",
                           writing_agent_raw="LONG, DONALD"),
    ])
    db.session.flush()

    out = retired_agent_breakdown(agency_id)
    assert out[0]["writing_agent"] == "LONG, DONALD", \
        "the +$60 earner leads, not the -$250 chargeback"
    assert out[0]["agent_payout"] == 60.0
    assert out[-1]["agent_payout"] == -250.0
