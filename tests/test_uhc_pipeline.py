"""
tests/test_uhc_pipeline.py

UHC went live through the normalized pipeline (2026-06-11). These tests cover the
quarantine query helper that surfaces the NEEDS_MANUAL_REVIEW line items (the
~2.3% the parser can't auto-split) for AJ's quarantine tab.
"""
from datetime import date


def _mk_stmt(db, agency, period="May 2026"):
    from app.models import CommissionStatement
    s = CommissionStatement(agency_id=agency.id, carrier="UHC", agent_id=None,
                            period_label=period, filename="uhc.xlsx",
                            statement_date=date(2026, 5, 1))
    db.session.add(s); db.session.flush()
    return s


def _mk_li(db, agency, stmt, *, cls, raw, name, ptype=None, ref):
    from app.models import CommissionLineItem
    li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                            period_label=stmt.period_label, source_ref=ref,
                            member_name=name, raw_amount=raw, split_rate=None,
                            classification=cls, payment_type=ptype)
    db.session.add(li); db.session.flush()
    return li


def test_quarantined_line_items_returns_only_needs_review(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="agent_commission", raw=28.92, name="OK, ONE", ref="uhc::0::1")
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=517.50, name="NEW, ALICE",
               ptype="New", ref="uhc::0::2")
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=0.26, name="DUST, BOB",
               ptype="partd dust", ref="uhc::0::3")
        db.session.commit()

        q = quarantined_line_items(stmt.id, agency.id)
        assert q["count"] == 2
        assert round(q["total"], 2) == round(517.50 + 0.26, 2)
        names = {r["member_name"] for r in q["rows"]}
        assert names == {"NEW, ALICE", "DUST, BOB"}
        # the auto-split row is NOT in the quarantine list
        assert "OK, ONE" not in names


def test_quarantined_line_items_empty_when_none(db_session, app, agency):
    from app.extensions import db
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="agent_commission", raw=28.92, name="OK, ONE", ref="uhc::0::1")
        db.session.commit()

        q = quarantined_line_items(stmt.id, agency.id)
        assert q["count"] == 0
        assert q["total"] == 0.0
        assert q["rows"] == []


def test_quarantine_page_renders_for_admin(db_session, app, client, agency):
    """The quarantine review page renders end-to-end through the route + template
    (catches context-processor/template regressions, not just the helper)."""
    from app.extensions import db
    from app.models import User

    with app.app_context():
        admin = User(name="AJ", email="admin@test.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin); db.session.flush()
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=517.50,
               name="NEW, ALICE", ptype="New", ref="uhc::0::2")
        db.session.commit()
        sid, uid = stmt.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(uid)
    resp = client.get(f"/admin/commissions/{sid}/quarantine")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "NEW, ALICE" in body
    assert "Quarantine" in body


def test_long_quarantine_action_string_persists(db_session, app, agency):
    """A real UHC quarantine row stores the full Commission Action description
    (~95 chars). It must persist (the column was VARCHAR(32) and broke uploads
    with StringDataRightTruncation — regression guard for migration 026)."""
    from app.extensions import db
    from app.models import CommissionLineItem

    long_action = ("New, DVH Manual Payment, DVH 1000 Plan, 09/01/2025 eff, "
                   "Policy 450396656, written by 6435806 for JANA BENSON, State: NC,")
    assert len(long_action) > 32

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        _mk_li(db, agency, stmt, cls="needs_manual_review", raw=29.53,
               name="BENSON, JANA", ptype=long_action, ref="uhc::0::30")
        db.session.commit()  # MUST NOT raise StringDataRightTruncation

        li = CommissionLineItem.query.filter_by(statement_id=stmt.id).first()
        assert li.payment_type == long_action  # stored in full, not truncated


def test_uhc_ha_payment_is_hra_bonus_with_member_name():
    """A UHC 'HA payment' is an HRA bonus (its own group), not a renewal, and its
    member name is parsed out of the action string (the HA rows have no member col)."""
    from app.commission.ledger import extract_lineitems_uhc, HRA_BONUS, CHARGEBACK, _uhc_ha_member

    assert _uhc_ha_member(
        "HA payment for agent ID 6337213 for member JEANETTE CATHCART MBI *****8VD98 policy 942") \
        == "JEANETTE CATHCART"

    header = [""] * 24
    header[5] = "Writing Agent Name"; header[7] = "Member Name"; header[8] = "MedicareID"
    header[12] = "Plan Type"; header[19] = "Commission Action"; header[23] = "Commission"
    def ha_row(action, amt):
        r = [""] * 24
        r[5] = "WINSLOW, TIMOTHY"; r[12] = "MAPD"; r[19] = action; r[23] = amt
        return r
    sheets = {"Commission Transactions": [
        header,
        ha_row("HA payment for agent ID 1 for member JANE DOE MBI *****1234 policy 9", 50.0),
        ha_row("HA chargeback for agent ID 1 for member BOB ROE MBI  policy 8", -50.0),
    ]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55)
    by_member = {i.member_name: i for i in items}
    assert by_member["JANE DOE"].classification == HRA_BONUS
    assert by_member["JANE DOE"].payment_type == "hra"
    assert by_member["BOB ROE"].classification == CHARGEBACK   # negative HA = clawback


def test_uhc_partd_026_is_founders_override_not_quarantined():
    """The fixed $0.26 PARTD renewal is a Founders override for a Part D plan (per
    Tim) — book it as founders_override (100% Founders, no split), NOT quarantine."""
    from app.commission.ledger import extract_lineitems_uhc, FOUNDERS_OVERRIDE, NEEDS_MANUAL_REVIEW

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[7] = "Member Name"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"
    def row(plan, action, amt, member="DOE, JANE"):
        r = [""] * 24
        r[5] = "WINSLOW, TIMOTHY"; r[7] = member; r[12] = plan; r[19] = action; r[23] = amt
        return r
    sheets = {"Commission Transactions": [
        header,
        row("PARTD", "Renewal", 0.26, "PARTD, OVR"),    # the override
        row("PARTD", "Renewal", 4.59, "PARTD, BIG"),    # already an override
        row("PARTD", "Renewal", 0.50, "PARTD, ODD"),    # other sub-$1 still quarantines
    ]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name={})
    by_member = {i.member_name: i for i in items}
    assert by_member["PARTD, OVR"].classification == FOUNDERS_OVERRIDE
    assert by_member["PARTD, OVR"].split_rate is None     # 100% Founders
    assert by_member["PARTD, BIG"].classification == FOUNDERS_OVERRIDE
    assert by_member["PARTD, ODD"].classification == NEEDS_MANUAL_REVIEW  # unchanged


def test_uhc_dvh_manual_payment_extracts_member_and_agent():
    """A DVH Manual Payment row has no member column — the member name + writing
    agent ID live inside the action string. The parser must pull the name out so the
    quarantine row isn't '(unnamed)', and resolve the writing agent via the ID map."""
    from app.commission.ledger import (extract_lineitems_uhc, NEEDS_MANUAL_REVIEW,
                                        _uhc_dvh_member, _uhc_dvh_agent_id)

    action = ("New, DVH Manual Payment, DVH 1000 Plan, 09/01/2025 eff, "
              "Policy 450396656, written by 6435806 for JANA BENSON, State: NC, "
              "Original Premium: $62.84")
    assert _uhc_dvh_member(action) == "JANA BENSON"
    assert _uhc_dvh_agent_id(action) == "6435806"

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[7] = "Member Name"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(amt):
        r = [""] * 24
        r[4] = ""               # no writing-id in col 4 either; only in the string
        r[7] = ""               # NO member column
        r[12] = "DVH"; r[19] = action; r[23] = amt
        return r

    sheets = {"Commission Transactions": [header, row(29.53)]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name={"6435806": "Rebekah Long"})
    assert len(items) == 1
    li = items[0]
    assert li.classification == NEEDS_MANUAL_REVIEW   # still quarantined
    assert li.member_name == "JANA BENSON"            # name pulled from the action
    assert li.writing_agent_raw == "Rebekah Long"     # agent resolved via the ID map


def test_uhc_new_125_is_founders_override_not_quarantined():
    """A flat $125.00 'New' UHC row is a 100% Founders override (no agent split) —
    a fixed referral/override fee that appears alongside the real New-enrollment
    commission (per Tim, June 2026). Book it as founders_override, not quarantine.
    Other 'New' amounts (the real enrollment commission) stay quarantined."""
    from app.commission.ledger import (extract_lineitems_uhc, FOUNDERS_OVERRIDE,
                                        NEEDS_MANUAL_REVIEW)

    header = [""] * 24
    header[5] = "Writing Agent Name"; header[7] = "Member Name"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(member, action, amt):
        r = [""] * 24
        r[5] = "FREEMAN, BRIAN"; r[7] = member; r[12] = "MAPD"
        r[19] = action; r[23] = amt
        return r

    sheets = {"Commission Transactions": [
        header,
        row("CORUM, TAMMY", "New", 125.0),     # the flat override
        row("CORUM, TAMMY", "New", 202.42),    # the real enrollment — still quarantines
    ]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name={})
    by_amt = {round(float(i.raw_amount), 2): i for i in items}
    assert by_amt[125.0].classification == FOUNDERS_OVERRIDE
    assert by_amt[125.0].split_rate is None                  # 100% Founders, no split
    assert by_amt[202.42].classification == NEEDS_MANUAL_REVIEW  # real New still quarantines


def test_uhc_medsupp_pair_splits_for_any_agent():
    """AARP Med-Supp pays per member as TWO lines (variable premium): a larger
    renewal (splits agent/Founders) + a smaller Founders override (no split). This
    must auto-split for ANY agent, not just a hardcoded LOA list — the June 2026
    bug where DEVA/PATEL/KENDALL (agents NOT on the old whitelist) fell to
    quarantine instead of splitting."""
    from app.commission.ledger import (extract_lineitems_uhc, AGENT_COMMISSION,
                                        FOUNDERS_OVERRIDE, NEEDS_MANUAL_REVIEW)

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[5] = "Writing Agent Name"
    header[7] = "Member Name"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(member, amt, agent="PATEL, ANJANA"):
        r = [""] * 24
        r[5] = agent; r[7] = member; r[12] = "AARPMODMEDSUP"
        r[19] = "Renewal"; r[23] = amt
        return r

    # A non-whitelisted agent's Med-Supp pair: larger 22.46 + smaller 2.98.
    sheets = {"Commission Transactions": [
        header,
        row("DEVA, HANSA", 25.21), row("DEVA, HANSA", 3.35),
        row("PATEL, ASHOK", 22.46), row("PATEL, ASHOK", 2.98),
    ]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name={})
    # group amounts by classification
    by_amt = {round(float(i.raw_amount), 2): i.classification for i in items}
    assert by_amt[25.21] == AGENT_COMMISSION    # larger line splits
    assert by_amt[3.35] == FOUNDERS_OVERRIDE     # smaller line = override, no split
    assert by_amt[22.46] == AGENT_COMMISSION
    assert by_amt[2.98] == FOUNDERS_OVERRIDE
    # none should land in quarantine
    assert NEEDS_MANUAL_REVIEW not in by_amt.values()
    # the override lines carry no split rate (100% Founders)
    overrides = [i for i in items if i.classification == FOUNDERS_OVERRIDE]
    assert all(o.split_rate is None for o in overrides)


def test_uhc_single_medsupp_line_without_pair_still_quarantines():
    """A lone AARP Med-Supp line (no matching pair for that member) can't be
    decomposed into renewal+override — it stays quarantined for AJ."""
    from app.commission.ledger import extract_lineitems_uhc, NEEDS_MANUAL_REVIEW

    header = [""] * 24
    header[5] = "Writing Agent Name"; header[7] = "Member Name"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(member, amt):
        r = [""] * 24
        r[5] = "PATEL, ANJANA"; r[7] = member; r[12] = "AARPMODMEDSUP"
        r[19] = "Renewal"; r[23] = amt
        return r

    sheets = {"Commission Transactions": [header, row("SOLO, MEMBER", 25.21)]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name={})
    assert all(i.classification == NEEDS_MANUAL_REVIEW for i in items)


def test_uhc_attributes_by_writing_agent_id_not_name():
    """Rebekah Long writes UHC under the agency name 'FOUNDERS INSURANCE AGENCY,
    LLC' but her Writing Agent ID (col 4) = 6435806. The parser MUST attribute by
    that ID, not the name (every row's name is the agency). Regression for the
    'Rebekah has 0 UHC' bug."""
    from app.commission.ledger import extract_lineitems_uhc

    id_to_name = {"6435806": "Rebekah Long", "6453223": "Christopher Foster"}

    header = [""] * 24
    header[4] = "Writing Agent ID"; header[5] = "Writing Agent Name"
    header[7] = "Member Name"; header[8] = "MedicareID"; header[12] = "Plan Type"
    header[19] = "Commission Action"; header[23] = "Commission"

    def row(wid, name, member, amt):
        r = [""] * 24
        r[4] = wid; r[5] = name; r[7] = member; r[12] = "MAPD"
        r[19] = "Renewal"; r[23] = amt
        return r

    sheets = {"Commission Transactions": [
        header,
        row("6435806", "FOUNDERS INSURANCE AGENCY, LLC", "DOE, JANE", 28.92),
        row("6453223", "FOSTER, CHRISTOPHER", "ROE, BOB", 28.92),
    ]}
    items = extract_lineitems_uhc(sheets, split_lookup=lambda raw: 0.55,
                                  writing_id_to_name=id_to_name)
    by_member = {i.member_name: i for i in items
                 if i.classification != "founders_override"}
    # Rebekah's row resolves to her name, NOT the agency string
    assert by_member["DOE, JANE"].writing_agent_raw == "Rebekah Long"
    assert by_member["ROE, BOB"].writing_agent_raw == "Christopher Foster"


def test_betty_riddle_legal_name_resolves_to_betty_marlowe(db_session, app, agency):
    """Betty writes some UHC business under her legal name 'RIDDLE, BETTY B'. It
    must resolve to her portal user (Betty Marlowe), not fall through unmatched."""
    from app.extensions import db
    from app.models import User
    from app.commission.routes import _match_agent_name

    with app.app_context():
        betty = User(name="Betty Marlowe", email="betty@test.com", agency_id=agency.id)
        db.session.add(betty); db.session.flush()
        assert _match_agent_name("RIDDLE, BETTY B") == betty.id
        assert _match_agent_name("Betty Marlowe") == betty.id   # her portal name still works


def test_quarantined_line_items_scoped_to_statement_and_agency(db_session, app, agency):
    """Must not leak quarantine rows from another statement or another agency."""
    from app.extensions import db
    from app.models import Agency
    from app.commission.recap import quarantined_line_items

    with app.app_context():
        other = Agency(name="Other Agency")
        db.session.add(other); db.session.flush()

        s1 = _mk_stmt(db, agency)
        s2 = _mk_stmt(db, agency, period="June 2026")
        _mk_li(db, agency, s1, cls="needs_manual_review", raw=100.0, name="S1", ref="uhc::0::1")
        _mk_li(db, agency, s2, cls="needs_manual_review", raw=200.0, name="S2", ref="uhc::0::1")
        db.session.commit()

        q1 = quarantined_line_items(s1.id, agency.id)
        assert q1["count"] == 1 and q1["rows"][0]["member_name"] == "S1"
        # wrong agency → nothing
        assert quarantined_line_items(s1.id, other.id)["count"] == 0


def test_resolve_quarantine_line_splits_into_commission_and_override(db_session, app, agency):
    """Resolving a quarantined 'New' row: AJ sets agent + override $; the remainder
    becomes agent_commission at the agent's split rate, override becomes a 100%-
    Founders line. Σ raw is unchanged; the row leaves quarantine."""
    from app.extensions import db
    from app.models import User, CommissionLineItem
    from app.commission.ledger import (resolve_quarantine_line, split_breakdown,
                                        AGENT_COMMISSION, FOUNDERS_OVERRIDE, NEEDS_MANUAL_REVIEW)

    with app.app_context():
        agent = User(name="Rebekah Long", email="rq@x.com", agency_id=agency.id)
        db.session.add(agent); db.session.flush()
        stmt = _mk_stmt(db, agency)
        li = _mk_li(db, agency, stmt, cls=NEEDS_MANUAL_REVIEW, raw=517.50,
                    name="NEW, ALICE", ptype="New", ref="uhc::0::2")
        db.session.commit()

        # AJ: agent=Rebekah, override $55.00, split 0.50 → commission part $462.50
        resolve_quarantine_line(li, agent.id, override_amount=55.00, split_rate=0.50)
        db.session.commit()

        rows = CommissionLineItem.query.filter_by(statement_id=stmt.id).all()
        by_class = {r.classification: r for r in rows}
        assert NEEDS_MANUAL_REVIEW not in by_class            # left quarantine
        comm = by_class[AGENT_COMMISSION]; ovr = by_class[FOUNDERS_OVERRIDE]
        assert round(comm.raw_amount, 2) == 462.50 and comm.agent_id == agent.id
        assert round(comm.split_rate, 2) == 0.50
        assert round(ovr.raw_amount, 2) == 55.00 and ovr.split_rate is None
        # Σ raw unchanged (balance invariant)
        assert round(comm.raw_amount + ovr.raw_amount, 2) == 517.50
        # agent payout = 462.50 * 0.50; override is 100% Founders keep
        assert round(split_breakdown(comm)[0], 2) == 231.25
        assert split_breakdown(ovr) == (0.0, 55.00)


def test_resolve_quarantine_override_zero_no_override_row(db_session, app, agency):
    """Override $0 → just attribute the whole amount as agent_commission, no override row."""
    from app.extensions import db
    from app.models import User, CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, AGENT_COMMISSION, FOUNDERS_OVERRIDE

    with app.app_context():
        agent = User(name="Tim Winslow", email="tq@x.com", agency_id=agency.id)
        db.session.add(agent); db.session.flush()
        stmt = _mk_stmt(db, agency)
        li = _mk_li(db, agency, stmt, cls="needs_manual_review", raw=100.0,
                    name="X", ref="uhc::0::9")
        db.session.commit()
        resolve_quarantine_line(li, agent.id, override_amount=0.0, split_rate=0.55)
        db.session.commit()
        rows = CommissionLineItem.query.filter_by(statement_id=stmt.id).all()
        assert len(rows) == 1
        assert rows[0].classification == AGENT_COMMISSION
        assert round(rows[0].raw_amount, 2) == 100.00
        assert FOUNDERS_OVERRIDE not in {r.classification for r in rows}


def test_quarantine_resolve_endpoint(db_session, app, client, agency):
    """End-to-end: POST resolve a quarantine line → it splits and leaves quarantine."""
    from app.extensions import db
    from app.models import User, CommissionLineItem, AgentCarrierContract
    with app.app_context():
        admin = User(name="AJ", email="qra@x.com", is_admin=True, agency_id=agency.id)
        reb = User(name="Rebekah Long", email="qrr@x.com", agency_id=agency.id)
        db.session.add_all([admin, reb]); db.session.flush()
        db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=reb.id,
                       carrier="UHC", is_active=True, split_rate=0.55))
        stmt = _mk_stmt(db, agency)
        li = _mk_li(db, agency, stmt, cls="needs_manual_review", raw=517.50,
                    name="NEW, ALICE", ptype="New", ref="uhc::0::2")
        db.session.commit()
        lid, uid, rid, sid = li.id, admin.id, reb.id, stmt.id

    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    r = client.post(f"/admin/commissions/line/{lid}/resolve",
                    data={"agent_id": rid, "override_amount": "55.00"})
    assert r.status_code in (302, 303)
    with app.app_context():
        from app.commission.recap import quarantined_line_items
        q = quarantined_line_items(sid, agency.id)
        assert q["count"] == 0   # resolved → gone from quarantine
        rows = CommissionLineItem.query.filter_by(statement_id=sid).all()
        classes = {x.classification for x in rows}
        assert "agent_commission" in classes and "founders_override" in classes


def test_resolve_endpoint_records_revision(db_session, app, client, agency):
    """The resolve endpoint must persist a revision (audit + undo) for the action."""
    from app.extensions import db
    from app.models import (CommissionStatement, CommissionLineItem, User,
                            CommissionLineItemRevision, AgentCarrierContract)
    from datetime import date
    with app.app_context():
        admin = User(email="admin@test.com", name="Admin", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        stmt = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                   statement_date=date(2026, 6, 1), period_label="June 2026")
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.commit()
        line_id, sid, aid = li.id, stmt.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    resp = client.post(f"/admin/commissions/line/{line_id}/resolve",
                       data={"agent_id": str(aid), "override_amount": "4.59"},
                       follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        assert CommissionLineItemRevision.query.filter_by(
            line_item_id=line_id, action="resolve").count() == 1


def test_period_quarantine_spans_carriers(db_session, app, agency):
    """period_quarantine aggregates needs_manual_review across ALL carriers/statements
    for a period, with a per-carrier breakdown (not UHC-specific)."""
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem
    from app.commission.recap import period_quarantine
    from datetime import date

    with app.app_context():
        for carrier, raw in [("UHC", 517.50), ("Aetna", 100.00), ("Aetna", 50.00)]:
            st = (CommissionStatement.query
                  .filter_by(agency_id=agency.id, carrier=carrier, period_label="May 2026").first())
            if not st:
                st = CommissionStatement(agency_id=agency.id, carrier=carrier, agent_id=None,
                                         period_label="May 2026", filename="x.xlsx",
                                         statement_date=date(2026,5,1))
                db.session.add(st); db.session.flush()
            db.session.add(CommissionLineItem(agency_id=agency.id, statement_id=st.id,
                           carrier=carrier, period_label="May 2026",
                           source_ref=f"{carrier}::q::{raw}", member_name=f"M{raw}",
                           raw_amount=raw, split_rate=None, classification="needs_manual_review"))
        db.session.commit()

        q = period_quarantine(agency.id, "May 2026")
        assert q["count"] == 3
        assert round(q["total"], 2) == 667.50
        assert set(q["by_carrier"]) == {"UHC", "Aetna"}
        assert q["by_carrier"]["Aetna"]["count"] == 2
        assert {r["carrier"] for r in q["rows"]} == {"UHC", "Aetna"}


def test_commission_review_redirects_to_workbench(db_session, app, client, agency):
    """The old period-level review page is RETIRED — it now redirects to the unified
    Quarantine Workbench (preserving the period) so there is one canonical surface."""
    from app.extensions import db
    from app.models import User
    with app.app_context():
        admin = User(name="AJ", email="rev@x.com", is_admin=True, agency_id=agency.id)
        db.session.add(admin); db.session.commit()
        uid = admin.id
    with client.session_transaction() as s:
        s["_user_id"] = str(uid)
    r = client.get("/admin/commissions/review?period=May%202026", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/admin/commissions/quarantine" in r.headers["Location"]
    assert "May" in r.headers["Location"]   # period preserved as a filter


def test_undo_endpoint_reverts_a_resolve(db_session, app, client, agency):
    from app.extensions import db
    from app.models import CommissionStatement, CommissionLineItem, User
    from app.commission.ledger import resolve_quarantine_line
    from datetime import date
    with app.app_context():
        admin = User(email="admin2@test.com", name="Admin2", is_admin=True, agency_id=agency.id)
        db.session.add(admin)
        stmt = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                   statement_date=date(2026, 6, 1), period_label="June 2026")
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=admin.id, override_amount=4.59,
                                split_rate=0.55, user_id=admin.id)
        db.session.commit()
        line_id, aid = li.id, admin.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    resp = client.post(f"/admin/commissions/line/{line_id}/undo", follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        from app.models import CommissionLineItem
        li2 = CommissionLineItem.query.get(line_id)
        assert li2.classification == "needs_manual_review"   # back to quarantine
        assert li2.raw_amount == 33.51


def test_edit_endpoint_uses_agent_contract_rate(db_session, app, client, agency):
    """The edit endpoint must derive the split rate from the agent's REAL
    AgentCarrierContract (0.525 here), never a hardcoded 0.55 — a silent wrong
    rate would corrupt pay (e.g. Betty Marlowe is 52.5%, not 55%)."""
    from app.extensions import db
    from app.models import (CommissionStatement, CommissionLineItem, User,
                            AgentCarrierContract)
    from datetime import date
    with app.app_context():
        admin = User(email="admin3@test.com", name="Admin3", is_admin=True, agency_id=agency.id)
        agent = User(email="agent3@test.com", name="Agent3", agency_id=agency.id)
        db.session.add_all([admin, agent]); db.session.flush()
        db.session.add(AgentCarrierContract(agency_id=agency.id, agent_id=agent.id,
                       carrier="UHC", split_rate=0.525, is_active=True))
        stmt = CommissionStatement(agency_id=agency.id, carrier="UHC",
                                   statement_date=date(2026, 6, 1), period_label="June 2026")
        db.session.add(stmt); db.session.flush()
        li = CommissionLineItem(agency_id=agency.id, statement_id=stmt.id, carrier="UHC",
                                source_ref="uhc::0::9", raw_amount=33.51, split_rate=None,
                                classification="agent_commission", payment_type="New")
        db.session.add(li); db.session.commit()
        line_id, aid, agent_id = li.id, admin.id, agent.id

    with client.session_transaction() as sess:
        sess["_user_id"] = str(aid)
    resp = client.post(f"/admin/commissions/line/{line_id}/edit",
                       data={"agent_id": str(agent_id), "agent_amount": "28.92",
                             "override_amount": "4.59"},
                       follow_redirects=False)
    assert resp.status_code in (302, 303)
    with app.app_context():
        from app.models import CommissionLineItem
        li2 = CommissionLineItem.query.get(line_id)
        assert li2.split_rate == 0.525   # NOT 0.55 — must derive from the contract
        sib = CommissionLineItem.query.filter_by(
            statement_id=li2.statement_id, source_ref=f"{li2.source_ref}::ovr").first()
        assert sib is not None
        assert sib.raw_amount == 4.59


def test_line_revisions_returns_history_newest_first(db_session, app, agency):
    from app.extensions import db
    from app.models import CommissionLineItem
    from app.commission.ledger import resolve_quarantine_line, undo_last_change
    from app.commission.recap import line_revisions
    with app.app_context():
        li = CommissionLineItem(agency_id=agency.id, statement_id=1, carrier="UHC",
                                source_ref="uhc::0::5", raw_amount=33.51, split_rate=None,
                                classification="needs_manual_review", payment_type="New")
        db.session.add(li); db.session.flush()
        resolve_quarantine_line(li, agent_id=7, override_amount=4.59, split_rate=0.55, user_id=3)
        db.session.flush()
        undo_last_change(li, user_id=3)
        db.session.commit()
        revs = line_revisions(li.id, agency.id)
        assert [r.action for r in revs] == ["undo", "resolve"]   # newest first


def test_recently_resolved_feed_batches_revisions(db_session, app, agency):
    """recently_resolved_line_items batches its revision fetch into one query
    instead of querying line_revisions() per row (was N+1) — this locks in that
    each row still carries its own correct revision history after the refactor."""
    from app.extensions import db
    from app.commission.ledger import resolve_quarantine_line
    from app.commission.recap import recently_resolved_line_items

    with app.app_context():
        stmt = _mk_stmt(db, agency)
        li1 = _mk_li(db, agency, stmt, cls="needs_manual_review", raw=10.00,
                     name="Alice One", ref="uhc::0::1")
        li2 = _mk_li(db, agency, stmt, cls="needs_manual_review", raw=20.00,
                     name="Bob Two", ref="uhc::0::2")
        resolve_quarantine_line(li1, agent_id=7, override_amount=1.00,
                                split_rate=0.55, user_id=3)
        resolve_quarantine_line(li2, agent_id=7, override_amount=2.00,
                                split_rate=0.55, user_id=3)
        db.session.commit()

        rows = recently_resolved_line_items(stmt.id, agency.id)
        assert len(rows) == 2
        by_id = {r["id"]: r for r in rows}
        assert li1.id in by_id and li2.id in by_id
        for r in by_id.values():
            assert len(r["revisions"]) >= 1
            assert r["revisions"][0].action == "resolve"
