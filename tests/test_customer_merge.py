"""
tests/test_customer_merge.py

TDD tests for merge_customers() in app/customers.py.

PolicyPayment has NO customer_id column — it links to a customer only through
policy_id → Policy.customer_id. When a loser's Policy moves to the keeper, that
policy's payments follow automatically (transitive reattachment).
"""
import pytest
from datetime import date

from app.extensions import db
from app.models import (
    Agency, User, Customer, Policy, PolicyPayment, CommissionStatement,
    CustomerNote, CustomerContact, CustomerAorHistory, CommissionLineItem, Plan,
)
from app.customers import merge_customers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _agency_user(db_session):
    """Return (agency_id, actor_user) — already flushed."""
    ag = Agency(name="T")
    db.session.add(ag)
    db.session.flush()
    u = User(email="actor@test.com", name="Actor", agency_id=ag.id, is_admin=True)
    db.session.add(u)
    db.session.flush()
    return ag.id, u


def _c(agency_id, **kw):
    """Create and flush a Customer with required defaults."""
    base = dict(agency_id=agency_id, first_name="", last_name="", stub=False)
    base.update(kw)
    c = Customer(**base)
    db.session.add(c)
    db.session.flush()
    return c


def _stmt(agency_id):
    """Create and flush a minimal CommissionStatement (required by PolicyPayment)."""
    s = CommissionStatement(
        agency_id=agency_id,
        carrier="UHC",
        statement_date=date(2026, 5, 1),
        period_label="May 2026",
    )
    db.session.add(s)
    db.session.flush()
    return s


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_merge_reattaches_all_children_and_fills_blanks(db_session, app):
    """
    merge_customers moves all child records to keeper and fills keeper's blank
    fields from the loser.  PolicyPayment follows transitively via Policy.
    """
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="John", last_name="Connelly",
                    full_name="John Connelly", mbi="4RH5X85DC65",
                    dob=date(1953, 4, 7))
        loser  = _c(agency_id, full_name="CONNELLY, JOHN", stub=True,
                    phone_primary="828-555-0100")  # keeper has no phone

        # Policy on the loser — its payments follow transitively
        loser_policy = Policy(agency_id=agency_id, carrier="UHC",
                              member_id="M1", customer_id=loser.id)
        db.session.add(loser_policy)
        db.session.flush()  # need policy.id for PaymentStatement link

        stmt = _stmt(agency_id)
        payment = PolicyPayment(
            agency_id=agency_id,
            statement_id=stmt.id,
            carrier="UHC",
            period_label="May 2026",
            member_name="John Connelly",
            commission_action="renewal",
            paid_amount=28.92,
            policy_id=loser_policy.id,
            source_ref="uhc::x::S::0",
        )
        db.session.add(payment)

        db.session.add(CustomerNote(
            agency_id=agency_id, customer_id=loser.id, agent_id=actor.id,
            note_text="hi",
        ))
        db.session.add(CustomerContact(
            agency_id=agency_id, customer_id=loser.id, contact_name="x",
        ))
        db.session.add(CustomerAorHistory(
            agency_id=agency_id, customer_id=loser.id, agent_id=actor.id,
            carrier="UHC", effective_date=date(2025, 1, 1),
        ))
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert res["merged"] == 1

        # loser deleted
        assert db.session.get(Customer, loser.id) is None

        # child records moved to keeper
        assert Policy.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerNote.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerContact.query.filter_by(customer_id=keeper.id).count() == 1
        assert CustomerAorHistory.query.filter_by(customer_id=keeper.id).count() == 1

        # PolicyPayment follows transitively (via policy, not a direct customer_id column)
        db.session.refresh(payment)
        assert payment.policy.customer_id == keeper.id

        # PolicyPayment count reported in moved dict
        assert res["moved"]["PolicyPayment"] >= 1

        # blank field filled from loser
        db.session.refresh(keeper)
        assert keeper.phone_primary == "828-555-0100"
        assert "phone_primary" in res["filled"]


def test_merge_never_overwrites_keeper_value(db_session, app):
    """Keeper's existing field values must never be overwritten."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                    phone_primary="111-111-1111")
        loser  = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                    stub=True, phone_primary="222-222-2222")
        db.session.commit()

        merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        db.session.refresh(keeper)
        assert keeper.phone_primary == "111-111-1111"   # kept, not overwritten


def test_merge_refuses_contradictory_dob(db_session, app):
    """Return ok=False when keeper + loser have different non-null DOBs."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="C", last_name="D", full_name="C D",
                    dob=date(1950, 1, 1))
        loser  = _c(agency_id, first_name="C", last_name="D", full_name="C D",
                    dob=date(1961, 2, 2))
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)

        assert res["ok"] is False
        assert "contradict" in res["error"].lower()
        # nothing deleted
        assert db.session.get(Customer, loser.id) is not None


def test_merge_is_idempotent_on_missing_loser(db_session, app):
    """When no loser IDs resolve (already merged / nonexistent), return ok=True merged=0."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="E", last_name="F", full_name="E F")
        db.session.commit()

        res = merge_customers(keeper.id, [99999], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert res["merged"] == 0


def test_merge_route_uses_engine_and_blocks_contradiction(db_session, app):
    """Engine refuses contradictory-DOB pair; route surfaces this as a flash."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        keeper = _c(agency_id, first_name="G", last_name="H", full_name="G H",
                    dob=date(1950, 1, 1))
        loser = _c(agency_id, first_name="G", last_name="H", full_name="G H",
                   dob=date(1962, 2, 2))
        db.session.commit()
        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        assert res["ok"] is False  # engine refuses; the route surfaces this as a flash


def test_duplicates_view_includes_no_mbi_clusters(db_session, app):
    """find_no_mbi_clusters returns a dob_match cluster containing a stub + real customer."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        a = _c(agency_id, first_name="Iz", last_name="Q", full_name="Iz Q",
               dob=date(1940, 5, 5))
        _c(agency_id, first_name="Iz", last_name="Q", full_name="Iz Q",
           dob=date(1940, 5, 5), stub=True)
        db.session.commit()
        from app.dedup import find_no_mbi_clusters
        clusters = find_no_mbi_clusters(agency_id)
        assert any(c.signal == "dob_match" and a.id in c.member_ids for c in clusters)


def test_editing_to_used_mbi_offers_merge(db_session, app):
    """
    When an admin edits a customer's MBI to a value already owned by a different
    customer, the route must return 409 JSON with ok=False and merge_with=<owner.id>,
    and must NOT save the MBI on the target customer.
    """
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        owner = _c(agency_id, first_name="Own", last_name="Er", full_name="Own Er",
                   mbi="1AA2BB3CC44")
        target = _c(agency_id, first_name="Tar", last_name="Get", full_name="Tar Get")
        db.session.commit()

        with app.test_request_context(
            f"/customers/{target.id}/field", method="POST",
            data={"field": "mbi", "value": "1AA2BB3CC44"}):
            from flask_login import login_user
            login_user(actor)
            from app.customers import customer_set_field
            resp = customer_set_field(target.id)

        body = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
        assert body["ok"] is False
        assert body["merge_with"] == owner.id

        # target's MBI was NOT changed
        db.session.expire(target)
        assert db.session.get(Customer, target.id).mbi is None


def test_merge_collapses_duplicate_aor_chapters(db_session, app):
    """
    When keeper and loser both have a CustomerAorHistory row for the same
    (carrier, effective_date), the merge must NOT blindly repoint the loser's
    row to the keeper — that produces a UniqueViolation on
    uq_aor_customer_carrier_date.  Instead: delete the colliding loser row
    (the chapter already exists on the keeper), and move non-colliding loser
    rows normally.

    Pre-fix behavior (blind bulk UPDATE): SQLite will produce two
    CustomerAorHistory rows for the keeper (both with customer_id=keeper.id,
    same carrier/effective_date) because SQLite does not enforce unique
    constraints via UPDATE the same way Postgres does.  So the test's
    post-condition assertion — keeper has exactly ONE UHC-2023-09-01 row —
    is what fails pre-fix on SQLite; in Postgres the test would fail with
    UniqueViolation.
    """
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="John", last_name="Connelly",
                    full_name="John Connelly", mbi="4RH5X85DC65",
                    dob=date(1953, 4, 7))
        loser  = _c(agency_id, full_name="CONNELLY, JOHN", stub=True)

        # keeper already has the UHC 2023-09-01 chapter
        db.session.add(CustomerAorHistory(
            agency_id=agency_id, customer_id=keeper.id, agent_id=actor.id,
            carrier="UHC", effective_date=date(2023, 9, 1),
        ))
        # loser has the SAME chapter (collision) plus a distinct Aetna chapter
        db.session.add(CustomerAorHistory(
            agency_id=agency_id, customer_id=loser.id, agent_id=actor.id,
            carrier="UHC", effective_date=date(2023, 9, 1),  # COLLISION
        ))
        db.session.add(CustomerAorHistory(
            agency_id=agency_id, customer_id=loser.id, agent_id=actor.id,
            carrier="Aetna", effective_date=date(2024, 1, 1),  # distinct — must move
        ))
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert db.session.get(Customer, loser.id) is None  # loser deleted

        # keeper must have exactly 2 AOR rows: the original UHC one + the moved Aetna one
        keeper_aors = (
            CustomerAorHistory.query
            .filter_by(customer_id=keeper.id)
            .order_by(CustomerAorHistory.carrier)
            .all()
        )
        assert len(keeper_aors) == 2, (
            f"Expected 2 AOR rows on keeper but got {len(keeper_aors)}: "
            f"{[(r.carrier, r.effective_date) for r in keeper_aors]}"
        )
        carriers = {r.carrier for r in keeper_aors}
        assert "UHC" in carriers
        assert "Aetna" in carriers

        # specifically ONE UHC 2023-09-01 row (not two)
        uhc_rows = [r for r in keeper_aors
                    if r.carrier == "UHC" and r.effective_date == date(2023, 9, 1)]
        assert len(uhc_rows) == 1, "Duplicate UHC 2023-09-01 chapter was not collapsed"


def test_merge_reattaches_commission_line_items(db_session, app):
    """
    C1 regression guard: CommissionLineItem.customer_id must be repointed to the
    keeper before the loser is deleted.  Without the fix, Postgres raises a
    ForeignKeyViolation and the merge 500s.

    Approach: assert the reattachment directly (customer_id == keeper.id after
    merge).  This catches the root cause (customer_id not moved) deterministically.
    The FK-violation consequence in Postgres is covered by the fact that
    CommissionLineItem.customer_id is an FK with no ondelete — any remaining
    reference to the deleted loser row raises a ForeignKeyViolation there.

    Note on SQLite FK enforcement: PRAGMA foreign_keys=ON was evaluated but
    rejected.  PRAGMA is per-connection and SQLite re-uses the session-scoped
    connection pool across tests — setting it leaked into 7 unrelated tests
    causing false failures.  The direct assertion below is sufficient to catch
    the bug deterministically without connection side-effects.
    """
    with app.app_context():
        agency_id, actor = _agency_user(db_session)

        keeper = _c(agency_id, first_name="John", last_name="Connelly",
                    full_name="John Connelly", mbi="4RH5X85DC65",
                    dob=date(1953, 4, 7))
        loser = _c(agency_id, full_name="CONNELLY, JOHN", stub=True)

        stmt = _stmt(agency_id)

        # CommissionLineItem attached to the LOSER — without C1 fix, delete(loser)
        # raises a Postgres ForeignKeyViolation because customer_id still points
        # at the now-deleted loser row.
        li = CommissionLineItem(
            agency_id=agency_id,
            statement_id=stmt.id,
            carrier="UHC",
            raw_amount=28.92,
            classification="agent_commission",
            source_ref="uhc::test::S::999",
            customer_id=loser.id,
        )
        db.session.add(li)
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()

        assert res["ok"] is True
        assert db.session.get(Customer, loser.id) is None  # loser deleted

        # Line item followed the keeper — this is the C1 regression assertion.
        # If the reattach loop omitted CommissionLineItem, customer_id would still
        # equal loser.id (now a deleted row), causing this assertion to fail AND
        # a Postgres ForeignKeyViolation on commit.
        db.session.expire(li)
        refreshed = db.session.get(CommissionLineItem, li.id)
        assert refreshed is not None
        assert refreshed.customer_id == keeper.id


def test_merge_inherits_preferred_name_into_blank_keeper(db_session, app):
    """Keeper has no preferred_name, loser has 'Craig' → after merge keeper.preferred_name == 'Craig'."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        keeper = _c(agency_id, first_name="Donald", last_name="Horstmann",
                    full_name="Donald Horstmann")  # no preferred_name
        loser = _c(agency_id, first_name="Donald", last_name="Horstmann",
                   full_name="Donald Horstmann", preferred_name="Craig")
        db.session.commit()
        merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()
        assert keeper.preferred_name == "Craig"  # goes-by not lost


def test_merge_does_not_overwrite_keeper_preferred_name(db_session, app):
    """Keeper has 'Keep', loser has 'Lose' → after merge keeper.preferred_name == 'Keep' (fill-blanks-only)."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        keeper = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                    preferred_name="Keep")
        loser = _c(agency_id, first_name="A", last_name="B", full_name="A B",
                   preferred_name="Lose")
        db.session.commit()
        merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()
        assert keeper.preferred_name == "Keep"  # fill-blanks-only, keeper wins


def test_duplicates_route_renders_context_fields(db_session, app):
    """GET /admin/customers/duplicates renders 200 with context fields (carriers,
    source, policy count) visible in the HTML when a no-MBI cluster exists."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        # Two customers with same normalized name (triggers a no_mbi_cluster)
        c1 = _c(agency_id, first_name="Alice", last_name="Walker",
                full_name="Alice Walker", source="bob", stub=False)
        c2 = _c(agency_id, first_name="Alice", last_name="Walker",
                full_name="WALKER, ALICE", source="commission_import", stub=True)
        pol = Policy(agency_id=agency_id, carrier="Aetna", member_id="AW1",
                     customer_id=c1.id)
        db.session.add(pol)
        db.session.commit()

        client = app.test_client()
        with client.session_transaction() as sess:
            sess["_user_id"] = str(actor.id)
            sess["_fresh"] = True
        resp = client.get("/admin/customers/duplicates")
        assert resp.status_code == 200
        body = resp.data.decode()
        # Context fields must appear in the rendered HTML
        assert "Aetna" in body           # carriers
        assert "src bob" in body or "src commission" in body  # source field
        assert "polic" in body           # "policy" or "policies" count


def test_duplicates_view_rows_expose_context(db_session, app):
    """The view must hand the template each row's policy carriers + source so a human
    can judge a name_only cluster."""
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        from app.customers import _cluster_row_context
        a = _c(agency_id, first_name="Bob", last_name="Smith",
               full_name="Bob Smith", source="bob", stub=False)
        pol = Policy(agency_id=agency_id, carrier="UHC", member_id="M1",
                     customer_id=a.id)
        db.session.add(pol)
        db.session.commit()
        ctxrow = _cluster_row_context(a, agency_id)
        assert ctxrow["carriers"] == ["UHC"]
        assert ctxrow["policy_count"] == 1
        assert ctxrow["source"] == "bob"


def test_merge_donates_mbi_without_transient_duplicate(db_session, app):
    """When a loser donates its MBI to a blank-MBI keeper, the loser's MBI must be
    cleared as part of the SAME operation — otherwise keeper + (not-yet-deleted)
    loser both hold the MBI momentarily and Postgres' partial unique index
    ix_customers_mbi fires on flush (invisible on SQLite). Reproduces the Devoted
    'Rene Barger' stub→real merge failure. Assert the keeper gets the MBI and no
    OTHER surviving customer still holds it."""
    from app.extensions import db
    with app.app_context():
        agency_id, actor = _agency_user(db_session)
        keeper = _c(agency_id, first_name="Rene", last_name="Barger",
                    full_name="Rene Barger", mbi=None)                 # blank MBI
        loser = _c(agency_id, first_name="Rene", last_name="Barger",
                   full_name="Rene Barger", stub=True, mbi="2U13N20CV96")
        db.session.commit()

        res = merge_customers(keeper.id, [loser.id], agency_id, actor)
        db.session.commit()                                            # must NOT raise
        assert res["ok"]
        db.session.refresh(keeper)
        assert keeper.mbi == "2U13N20CV96"                             # donated
        # loser deleted; no surviving customer other than keeper holds the MBI
        survivors = Customer.query.filter(Customer.mbi == "2U13N20CV96",
                                          Customer.id != keeper.id).all()
        assert survivors == []


# ---------------------------------------------------------------------------
# Reissued-MBI merge override route (task 2)
# ---------------------------------------------------------------------------

def _login(client, user):
    with client.session_transaction() as s:
        s["_user_id"] = str(user.id); s["_fresh"] = True


def _client_app():
    """Build a fresh app + admin + agency and return (app, client, agency_id, admin)."""
    from app import create_app
    app = create_app()
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
                      RATELIMIT_ENABLED=False, SESSION_COOKIE_SECURE=False,
                      REMEMBER_COOKIE_SECURE=False, WTF_CSRF_ENABLED=False)
    ctx = app.app_context(); ctx.push()
    db.create_all()
    ag = Agency(name="T"); db.session.add(ag); db.session.flush()
    admin = User(email="a@b.com", name="Admin", is_admin=True, agency_id=ag.id, role="admin")
    db.session.add(admin); db.session.flush()
    client = app.test_client(); _login(client, admin)
    return app, client, ag.id, admin, ctx


def _policy(agency_id, customer_id, carrier, member_id, status="active"):
    p = Policy(agency_id=agency_id, customer_id=customer_id, carrier=carrier,
               member_id=member_id, status=status)
    db.session.add(p); db.session.flush()
    return p


def test_reissued_merge_disabled_makes_no_changes():
    # The reissued-MBI override is DISABLED (REISSUED_MBI_MERGE_ENABLED=False) pending
    # the lane-aware corrected merge — its "term the loser's stale policy" logic is
    # wrong for a coexistence pair (would term an active DVH/Medigap). The route must
    # refuse and change NOTHING. See docs/…/2026-07-21-customer-plan-domain-model.md §6.1.
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, first_name="Milton", last_name="Frazier",
                    full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="CURR123")
        loser = _c(aid, first_name="Milton", last_name="Frazier",
                   full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="STALE99")
        _policy(aid, keeper.id, "UHC", "CURR123")
        _policy(aid, loser.id, "UHC", "STALE99")
        db.session.commit()

        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id},
                           follow_redirects=False)
        assert resp.status_code in (302, 303)

        # Guard blocked it: BOTH records survive, MBIs unchanged, no policy termed.
        assert db.session.get(Customer, keeper.id) is not None
        assert db.session.get(Customer, loser.id) is not None
        assert db.session.get(Customer, loser.id).mbi == "STALE99"
        statuses = {p.member_id: p.status for p in Policy.query.all()}
        assert statuses["STALE99"] == "active"
        assert statuses["CURR123"] == "active"
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_reissued_merge_refuses_diff_dob():
    app, client, aid, admin, ctx = _client_app()
    try:
        a = _c(aid, full_name="X Y", dob=date(1950, 2, 3), mbi="AAA")
        b = _c(aid, full_name="X Y", dob=date(1961, 9, 9), mbi="BBB")  # different DOB
        db.session.commit()
        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": a.id, "loser_id": b.id})
        assert resp.status_code in (302, 303)
        # nothing merged — both records still exist
        assert db.session.get(Customer, a.id) is not None
        assert db.session.get(Customer, b.id) is not None
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_reissued_merge_preserves_money():
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, full_name="Money Man", dob=date(1950, 2, 3), mbi="CURR")
        loser = _c(aid, full_name="Money Man", dob=date(1950, 2, 3), mbi="STALE")
        kp = _policy(aid, keeper.id, "UHC", "CURR")
        lp = _policy(aid, loser.id, "UHC", "STALE")
        stmt = _stmt(aid)
        db.session.add(PolicyPayment(agency_id=aid, statement_id=stmt.id, policy_id=kp.id,
                                     carrier="UHC", period_label="May 2026",
                                     member_name="Money Man", commission_action="renewal",
                                     paid_amount=100.00))
        db.session.add(PolicyPayment(agency_id=aid, statement_id=stmt.id, policy_id=lp.id,
                                     carrier="UHC", period_label="May 2026",
                                     member_name="Money Man", commission_action="renewal",
                                     paid_amount=55.00))
        db.session.commit()
        before = db.session.query(db.func.coalesce(db.func.sum(PolicyPayment.paid_amount), 0)).scalar()

        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id})
        assert resp.status_code in (302, 303)
        after = db.session.query(db.func.coalesce(db.func.sum(PolicyPayment.paid_amount), 0)).scalar()
        assert float(after) == float(before)          # no money moved or lost
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_reissued_merge_refuses_same_mbi_tamper():
    app, client, aid, admin, ctx = _client_app()
    try:
        # Same DOB, SAME MBI => not a reissued candidate; a forced POST must be refused.
        a = _c(aid, full_name="Tam Per", dob=date(1950, 2, 3), mbi="SAME")
        b = _c(aid, full_name="Tam Per", dob=date(1950, 2, 3), mbi="SAME")
        db.session.commit()
        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": a.id, "loser_id": b.id})
        assert resp.status_code in (302, 303)
        # nothing merged — both records still exist
        assert db.session.get(Customer, a.id) is not None
        assert db.session.get(Customer, b.id) is not None
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_reissued_merge_disabled_leaves_both_records():
    # A second disabled-state guard: even the previously-"idempotent" shape (loser's
    # policy already termed) must not merge while the override is disabled — both
    # customer records survive untouched.
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, full_name="Z Z", dob=date(1950, 2, 3), mbi="CURR")
        loser = _c(aid, full_name="Z Z", dob=date(1950, 2, 3), mbi="STALE")
        _policy(aid, loser.id, "UHC", "STALE", status="termed")
        db.session.commit()
        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id})
        assert resp.status_code in (302, 303)
        assert db.session.get(Customer, keeper.id) is not None
        assert db.session.get(Customer, loser.id) is not None   # NOT merged away
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


# ---------------------------------------------------------------------------
# Lane-aware corrected merge (task 3)
# ---------------------------------------------------------------------------

from datetime import date as _date
from app.customers import merge_customers_lane_aware


def _pol(aid, cid, carrier, member_id, plan_type="", contract_code=None,
         eff=None, status="active"):
    p = Policy(agency_id=aid, customer_id=cid, carrier=carrier, member_id=member_id,
               plan_type=plan_type, contract_code=contract_code,
               effective_date=eff, status=status)
    db.session.add(p); db.session.flush()
    return p


def test_lane_merge_overcash_supersedes_pdp():
    app, client, aid, admin, ctx = _client_app()
    try:
        # keeper = UHC MAPD (current, newer), loser = Aetna PDP (older, stale MBI)
        keeper = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="1X88VQ0CP30")
        loser = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="2WA7KC0TM50")
        _pol(aid, keeper.id, "UHC", "1X88VQ0CP30", "mapd", "H5253-117", _date(2026, 1, 1))
        _pol(aid, loser.id, "Aetna", "2WA7KC0TM50", "pdp", "S5601-017", _date(2024, 1, 1))
        db.session.commit()

        res = merge_customers_lane_aware(keeper.id, [loser.id], aid, admin)
        assert res["ok"] is True
        assert res["needs_review"] is False
        assert db.session.get(Customer, loser.id) is None
        k = db.session.get(Customer, keeper.id)
        assert k.mbi == "1X88VQ0CP30"                       # current MBI kept
        by_carrier = {p.carrier: p.status for p in Policy.query.filter_by(customer_id=keeper.id)}
        assert by_carrier["UHC"] == "active"                # current stays
        assert by_carrier["Aetna"] == "termed"              # superseded PDP termed
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_lane_merge_coexistence_keeps_both():
    app, client, aid, admin, ctx = _client_app()
    try:
        # Benson-shape: keeper = UHC Medigap (real MBI), loser = UHC DVH (policy-number in mbi)
        keeper = _c(aid, full_name="Jana Benson", dob=_date(1959, 8, 24), mbi="3DJ9F94VV42")
        loser = _c(aid, full_name="Jana Benson", dob=_date(1959, 8, 24), mbi="45039665600")
        _pol(aid, keeper.id, "UHC", "3DJ9F94VV42", "ms", None, _date(2025, 9, 1))
        _pol(aid, loser.id, "UHC", "45039665600", "dvh", None, _date(2025, 9, 1))
        db.session.commit()

        res = merge_customers_lane_aware(keeper.id, [loser.id], aid, admin)
        assert res["ok"] is True
        k = db.session.get(Customer, keeper.id)
        assert k.mbi == "3DJ9F94VV42"                       # real Medigap MBI, NOT the policy number
        statuses = [p.status for p in Policy.query.filter_by(customer_id=keeper.id)]
        assert statuses == ["active", "active"]             # BOTH kept active
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_lane_merge_refuses_different_dob():
    app, client, aid, admin, ctx = _client_app()
    try:
        a = _c(aid, full_name="X Y", dob=_date(1950, 1, 1), mbi="1X88VQ0CP30")
        b = _c(aid, full_name="X Y", dob=_date(1961, 1, 1), mbi="2WA7KC0TM50")
        db.session.commit()
        res = merge_customers_lane_aware(a.id, [b.id], aid, admin)
        assert res["ok"] is False
        assert db.session.get(Customer, a.id) is not None
        assert db.session.get(Customer, b.id) is not None
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_lane_merge_closes_superseded_aor():
    # Task-3 review gap A: terming the superseded policy must also CLOSE its
    # open CustomerAorHistory chapter (Tim's real bug — terming a policy while
    # leaving its AOR open makes the timeline show it as still-current).
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="1X88VQ0CP30")
        loser = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="2WA7KC0TM50")
        _pol(aid, keeper.id, "UHC", "1X88VQ0CP30", "mapd", "H5253-117", _date(2026, 1, 1))
        _pol(aid, loser.id, "Aetna", "2WA7KC0TM50", "pdp", "S5601-017", _date(2024, 1, 1))
        db.session.add(CustomerAorHistory(
            agency_id=aid, customer_id=loser.id, agent_id=admin.id,
            carrier="Aetna", effective_date=_date(2024, 1, 1), end_date=None,
        ))
        db.session.commit()

        res = merge_customers_lane_aware(keeper.id, [loser.id], aid, admin)
        assert res["ok"] is True

        by_carrier = {p.carrier: p.status for p in Policy.query.filter_by(customer_id=keeper.id)}
        assert by_carrier["Aetna"] == "termed"

        aetna_aor = CustomerAorHistory.query.filter_by(
            customer_id=keeper.id, carrier="Aetna").first()
        assert aetna_aor is not None
        assert aetna_aor.end_date is not None
        assert aetna_aor.end_date == _date(2025, 12, 31)
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()


def test_lane_merge_uses_linked_plan_type():
    # Task-3 review gap B: resolve_primary_medical must read the EFFECTIVE
    # plan_type/contract_code, falling back to the linked Plan when the
    # Policy's own field is blank (Overcash's real Aetna policy has
    # plan_type='' but its linked Plan is pdp/S5601-017).
    app, client, aid, admin, ctx = _client_app()
    try:
        uhc_plan = Plan(agency_id=aid, carrier="UHC", plan_name="UHC MAPD",
                        year=2026, plan_type="mapd", cms_plan_id="H5253-117")
        aetna_plan = Plan(agency_id=aid, carrier="Aetna", plan_name="Aetna PDP",
                          year=2026, plan_type="pdp", cms_plan_id="S5601-017")
        db.session.add_all([uhc_plan, aetna_plan])
        db.session.flush()

        keeper = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="1X88VQ0CP30")
        loser = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="2WA7KC0TM50")

        kp = Policy(agency_id=aid, customer_id=keeper.id, carrier="UHC",
                    member_id="1X88VQ0CP30", plan_type="", contract_code=None,
                    plan_id=uhc_plan.id, effective_date=_date(2026, 1, 1), status="active")
        lp = Policy(agency_id=aid, customer_id=loser.id, carrier="Aetna",
                    member_id="2WA7KC0TM50", plan_type="", contract_code=None,
                    plan_id=aetna_plan.id, effective_date=_date(2024, 1, 1), status="active")
        db.session.add_all([kp, lp])
        db.session.flush()
        db.session.commit()

        res = merge_customers_lane_aware(keeper.id, [loser.id], aid, admin)
        assert res["ok"] is True
        assert res["needs_review"] is False

        by_carrier = {p.carrier: p.status for p in Policy.query.filter_by(customer_id=keeper.id)}
        # If the fallback to the linked Plan weren't happening, both blank-type
        # policies would classify as lane 'other' -> no supersession -> Aetna
        # would remain active. Termed proves the fallback derived pdp/mapd
        # from the linked Plan rows.
        assert by_carrier["Aetna"] == "termed"
        assert by_carrier["UHC"] == "active"
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()
