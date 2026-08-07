"""
tests/test_ledger_backlink.py

Shared customer back-link resolution for commission ledger rows
(app/commission/backlink.py). SQLite in-memory via conftest fixtures.
"""
import pytest


@pytest.fixture
def ctx(db_session, app, agency):
    """Agency + a customer with one active policy + a paid statement."""
    from datetime import date
    from app.models import Customer, Policy, CommissionStatement

    with app.app_context():
        cust = Customer(agency_id=agency.id, first_name="Mary", last_name="Earnhardt",
                       full_name="Mary Earnhardt")
        db_session.add(cust)
        db_session.flush()

        pol = Policy(agency_id=agency.id, customer_id=cust.id, carrier="BCBS",
                     member_id="106703512", full_name="Mary Earnhardt",
                     status="active")
        db_session.add(pol)
        db_session.flush()

        stmt = CommissionStatement(agency_id=agency.id, carrier="BCBS",
                                   period_label="July 2026",
                                   statement_date=date(2026, 7, 1))
        db_session.add(stmt)
        db_session.flush()
        db_session.commit()

        yield app, agency.id, cust.id, pol.id, stmt.id


def test_resolves_via_payment_sibling(ctx):
    """Step 1: a payment row with the same source_ref carries the identity."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import PolicyPayment
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        db.session.add(PolicyPayment(agency_id=aid, statement_id=sid, carrier="BCBS",
                                     period_label="July 2026", member_name="Mary Earnhardt",
                                     commission_action="renewal", paid_amount=10.0,
                                     policy_id=pid, source_ref="bcbs::T::Sheet1::7"))
        db.session.commit()
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, statement_id=sid, source_ref="bcbs::T::Sheet1::7",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id=None, member_name=None)
        assert got == cid


def test_resolves_via_carrier_member_id_fallback(ctx):
    """Step 2: no payment sibling, but carrier_member_id matches a policy.
    This is the BCBS case that fails today — BCBS rows carry NO mbi."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, statement_id=sid, source_ref="bcbs::T::Sheet1::99",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name=None)
        assert got == cid


def test_returns_none_when_unresolvable(ctx):
    """No sibling, no id match, no name match -> None (caller must not overwrite)."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, statement_id=sid, source_ref="bcbs::T::Sheet1::404",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id="NO_SUCH_ID",
                                  member_name="Nobody Here")
        assert got is None


def test_payment_sibling_wins_over_tiers(ctx):
    """Step 1 takes precedence over step 2 when both could resolve."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import Customer, Policy, PolicyPayment
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        other = Customer(agency_id=aid, first_name="Other", last_name="Person",
                        full_name="Other Person")
        db.session.add(other)
        db.session.flush()
        opol = Policy(agency_id=aid, customer_id=other.id, carrier="BCBS",
                      member_id="999", full_name="Other Person", status="active")
        db.session.add(opol)
        db.session.flush()
        db.session.add(PolicyPayment(agency_id=aid, statement_id=sid, carrier="BCBS",
                                     period_label="July 2026", member_name="Other Person",
                                     commission_action="renewal", paid_amount=10.0,
                                     policy_id=opol.id, source_ref="bcbs::T::Sheet1::5"))
        db.session.commit()
        c = build_backlink_context(aid)
        # carrier_member_id points at cust, but the payment sibling points at other
        got = resolve_customer_id(c, statement_id=sid, source_ref="bcbs::T::Sheet1::5",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name=None)
        assert got == other.id


def test_agency_scoped(ctx):
    """A payment/policy in another agency must never resolve."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import Agency
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        ag2 = Agency(name="Other")
        db.session.add(ag2)
        db.session.flush()
        c = build_backlink_context(ag2.id)
        got = resolve_customer_id(c, statement_id=sid, source_ref="bcbs::T::Sheet1::7",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name="Mary Earnhardt")
        assert got is None


def test_agency_scoped_payment_sibling_join(ctx):
    """Regression for the by_source_ref join: it must filter Policy.agency_id
    explicitly, not rely solely on PolicyPayment.agency_id.

    Constructs the one case that actually exercises the missing filter: a
    PolicyPayment ROW STAMPED WITH AGENCY B's id (e.g. a stray/misattributed
    payment row) that nonetheless points (via policy_id) at agency A's real
    Policy/Customer. Building the context for agency B must NOT resolve this
    source_ref to agency A's customer — building it for agency B should only
    ever surface agency-B-owned links.

    test_agency_scoped does not cover this: there, ag2 has zero payments, so
    the map is trivially empty regardless of whether the Policy filter exists.
    Here agency B's map WOULD be non-empty (falsely) without the Policy.agency_id
    filter, because the PolicyPayment.agency_id == B filter alone is satisfied."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import Agency, PolicyPayment
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    with app.app_context():
        ag2 = Agency(name="Other")
        db.session.add(ag2)
        db.session.flush()

        # A payment stamped agency_id=ag2 but pointing at agency A's policy
        # (cross-agency data-quality edge case; the schema doesn't forbid it).
        db.session.add(PolicyPayment(agency_id=ag2.id, statement_id=sid, carrier="BCBS",
                                     period_label="July 2026", member_name="Mary Earnhardt",
                                     commission_action="renewal", paid_amount=10.0,
                                     policy_id=pid, source_ref="bcbs::T::Sheet1::7"))
        db.session.commit()

        c_b = build_backlink_context(ag2.id)
        got = resolve_customer_id(c_b, statement_id=sid, source_ref="bcbs::T::Sheet1::7",
                                  carrier="BCBS",
                                  mbi=None, carrier_member_id=None, member_name=None)
        assert got is None


def test_persist_never_erases_an_established_link(ctx):
    """THE REGRESSION TEST. A row that already has a customer_id must KEEP it
    when re-persisted with a draft that cannot be resolved. This is the BCBS
    199/216 -> 0/218 case."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionStatement
    from app.commission.ledger import persist_line_items, LineItemDraft
    with app.app_context():
        row = CommissionLineItem(
            agency_id=aid, statement_id=sid, carrier="BCBS",
            source_ref="bcbs::T::Sheet1::42", customer_id=cid,
            raw_amount=100.0, classification="agent_commission", split_rate=0.55)
        db.session.add(row); db.session.commit()
        # A draft with NOTHING resolvable — no sibling, no id, no known name.
        d = LineItemDraft(carrier="BCBS", source_ref="bcbs::T::Sheet1::42",
                          raw_amount=100.0, classification="agent_commission",
                          split_rate=0.55, member_name="Unknown Person",
                          mbi=None, carrier_member_id="NOPE")
        stmt = db.session.get(CommissionStatement, sid)
        persist_line_items("BCBS", [d], stmt, aid)
        db.session.commit()
        again = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::42").first()
        assert again.customer_id == cid       # link SURVIVED


def test_persist_links_bcbs_row_with_no_mbi(ctx):
    """BCBS carries carrier_member_id only. Today this links to nothing."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionStatement
    from app.commission.ledger import persist_line_items, LineItemDraft
    with app.app_context():
        d = LineItemDraft(carrier="BCBS", source_ref="bcbs::T::Sheet1::43",
                          raw_amount=50.0, classification="agent_commission",
                          split_rate=0.55, member_name="Mary Earnhardt",
                          mbi=None, carrier_member_id="106703512")
        stmt = db.session.get(CommissionStatement, sid)
        persist_line_items("BCBS", [d], stmt, aid)
        db.session.commit()
        row = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::43").first()
        assert row.customer_id == cid


def test_persist_does_not_touch_money_fields(ctx):
    """The fix must move customer_id ONLY."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import CommissionLineItem, CommissionStatement
    from app.commission.ledger import persist_line_items, LineItemDraft
    with app.app_context():
        d = LineItemDraft(carrier="BCBS", source_ref="bcbs::T::Sheet1::44",
                          raw_amount=123.45, classification="chargeback",
                          split_rate=0.525, member_name="Mary Earnhardt",
                          mbi=None, carrier_member_id="106703512")
        stmt = db.session.get(CommissionStatement, sid)
        persist_line_items("BCBS", [d], stmt, aid)
        db.session.commit()
        row = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::44").first()
        assert row.raw_amount == 123.45
        assert row.classification == "chargeback"
        assert row.split_rate == 0.525


def test_source_ref_is_scoped_per_statement_not_global(db_session, app, agency):
    """THE CRITICAL REGRESSION TEST. source_ref is only unique WITHIN a
    statement (aetna::0::147 is identical text in every monthly Aetna file);
    the composite (statement_id, source_ref) key is what the DB's own
    uq_payment_statement_source_ref / uq_lineitem_statement_source_ref
    constraints declare unique. Two DIFFERENT statements sharing the SAME
    source_ref string, each pointing at a DIFFERENT customer, must each
    resolve to their OWN customer — never to the other statement's customer.

    Constructed in BOTH insertion orders so the test cannot pass vacuously
    on an order-dependent dict-overwrite bug (which is exactly how the
    single-key version could look correct for one order and wrong for the
    other, depending on which row a plain `by_source_ref[sref] = cust_id`
    loop happened to write last)."""
    from datetime import date
    from app.models import Customer, Policy, CommissionStatement, PolicyPayment
    from app.commission.backlink import build_backlink_context, resolve_customer_id

    def _make_statement_customer_policy_payment(label, month, cust_name, member_id, sref):
        cust = Customer(agency_id=agency.id,
                       first_name=cust_name.split()[0], last_name=cust_name.split()[1],
                       full_name=cust_name)
        db_session.add(cust)
        db_session.flush()
        pol = Policy(agency_id=agency.id, customer_id=cust.id, carrier="Aetna",
                     member_id=member_id, full_name=cust_name, status="active")
        db_session.add(pol)
        db_session.flush()
        stmt = CommissionStatement(agency_id=agency.id, carrier="Aetna",
                                   period_label=label,
                                   statement_date=date(2026, month, 1))
        db_session.add(stmt)
        db_session.flush()
        db_session.add(PolicyPayment(agency_id=agency.id, statement_id=stmt.id,
                                     carrier="Aetna", period_label=label,
                                     member_name=cust_name, commission_action="renewal",
                                     paid_amount=10.0, policy_id=pol.id, source_ref=sref))
        db_session.commit()
        return stmt.id, cust.id

    with app.app_context():
        # Order A: May (customer A) inserted BEFORE June (customer B).
        sid_may, cid_a = _make_statement_customer_policy_payment(
            "May 2026", 5, "Aaron Abbott", "AAA111", "aetna::0::147")
        sid_jun, cid_b = _make_statement_customer_policy_payment(
            "June 2026", 6, "Beatrice Baker", "BBB222", "aetna::0::147")

        ctx = build_backlink_context(agency.id)
        got_may = resolve_customer_id(ctx, statement_id=sid_may,
                                      source_ref="aetna::0::147", carrier="Aetna",
                                      mbi=None, carrier_member_id=None, member_name=None)
        got_jun = resolve_customer_id(ctx, statement_id=sid_jun,
                                      source_ref="aetna::0::147", carrier="Aetna",
                                      mbi=None, carrier_member_id=None, member_name=None)
        assert got_may == cid_a
        assert got_jun == cid_b

        # Order B (reversed insertion): July (customer C) inserted BEFORE
        # August (customer D) — the opposite relative order from above.
        sid_aug, cid_d = _make_statement_customer_policy_payment(
            "August 2026", 8, "Diane Dexter", "DDD444", "aetna::0::200")
        sid_jul, cid_c = _make_statement_customer_policy_payment(
            "July 2026", 7, "Carl Carter", "CCC333", "aetna::0::200")

        ctx2 = build_backlink_context(agency.id)
        got_jul = resolve_customer_id(ctx2, statement_id=sid_jul,
                                      source_ref="aetna::0::200", carrier="Aetna",
                                      mbi=None, carrier_member_id=None, member_name=None)
        got_aug = resolve_customer_id(ctx2, statement_id=sid_aug,
                                      source_ref="aetna::0::200", carrier="Aetna",
                                      mbi=None, carrier_member_id=None, member_name=None)
        assert got_jul == cid_c
        assert got_aug == cid_d


def test_surnames_agree_handles_carrier_name_formats():
    """The gate must accept the real carrier formats, or it would refuse good links."""
    from scripts.backfill_ledger_customer_links import _surnames_agree
    # BCBS "Last,First M" / Humana "LAST FIRST M" / UHC "LAST, FIRST"
    assert _surnames_agree("Robinson,Keith M", "Keith M. Robinson")
    assert _surnames_agree("HELMS TERESSA D", "Teressa Helms")
    assert _surnames_agree("PRESSON, ROBIN", "Robin Presson")
    assert _surnames_agree("COUCHELL, JOHN", "John Couchell")
    # the real prod mis-link this gate exists to catch
    assert not _surnames_agree("COUCHELL, JOHN", "Andrea Horstmann")
    # a missing name on either side must REFUSE, never silently pass
    assert not _surnames_agree("", "John Couchell")
    assert not _surnames_agree("COUCHELL, JOHN", "")
    assert not _surnames_agree(None, "John Couchell")
    # different people who happen to share only a FIRST name must be refused
    assert not _surnames_agree("SMITH, JOHN", "John Couchell")
    assert not _surnames_agree("Wells,Kristie F", "Kristie Barnhardt")
    # a lone shared middle initial must never carry the match
    assert not _surnames_agree("Nash,Joan D", "Deborah D. Whitlock")


def test_backfill_refuses_a_name_mismatched_link(ctx):
    """A resolvable row whose member name disagrees with the target customer is
    REFUSED and left NULL — the COUCHELL,JOHN -> Andrea Horstmann case on prod.
    A wrong customer_id is invisible and permanent, so refusing beats guessing."""
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import CommissionLineItem, PolicyPayment
    from scripts.backfill_ledger_customer_links import backfill_ledger_links
    with app.app_context():
        # A payment sibling resolves this source_ref to the ctx customer (Mary
        # Earnhardt), but the ledger row's member is somebody else entirely.
        db.session.add(PolicyPayment(
            agency_id=aid, statement_id=sid, carrier="BCBS", policy_id=pid,
            source_ref="bcbs::T::Sheet1::88", period_label="July 2026",
            member_name="Mary Earnhardt", commission_action="renewal",
            paid_amount=10.0))
        db.session.add(CommissionLineItem(
            agency_id=aid, statement_id=sid, carrier="BCBS",
            source_ref="bcbs::T::Sheet1::88", customer_id=None,
            raw_amount=10.0, classification="agent_commission", split_rate=0.55,
            member_name="Horstmann, Andrea"))
        db.session.commit()

        res = backfill_ledger_links(aid, apply=True)
        assert res["refused_name_mismatch"] == 1
        assert res["resolved"] == 0
        db.session.expire_all()
        row = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::88").first()
        assert row.customer_id is None          # refused, left for a human


def test_backfill_is_idempotent_and_dry_run_is_safe(ctx):
    app, aid, cid, pid, sid = ctx
    from app.extensions import db
    from app.models import CommissionLineItem
    from scripts.backfill_ledger_customer_links import backfill_ledger_links
    with app.app_context():
        db.session.add(CommissionLineItem(
            agency_id=aid, statement_id=sid, carrier="BCBS",
            source_ref="bcbs::T::Sheet1::77", customer_id=None,
            raw_amount=10.0, classification="agent_commission", split_rate=0.55,
            member_name="Mary Earnhardt", carrier_member_id="106703512"))
        db.session.commit()

        dry = backfill_ledger_links(aid, apply=False)
        assert dry["resolved"] == 1
        row = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::77").first()
        assert row.customer_id is None          # dry run wrote NOTHING

        run1 = backfill_ledger_links(aid, apply=True)
        assert run1["resolved"] == 1
        db.session.expire_all()
        row = CommissionLineItem.query.filter_by(
            source_ref="bcbs::T::Sheet1::77").first()
        assert row.customer_id == cid

        run2 = backfill_ledger_links(aid, apply=True)
        assert run2["resolved"] == 0            # idempotent
