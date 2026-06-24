"""
tests/test_bob_upload.py

Tests for BOB bulk-upload robustness: in-file dedup of repeated (carrier,
member_id) rows (so a multi-plan member doesn't collide on uq_carrier_member),
and per-row isolation so one bad row can't 500 the whole upload.
"""


def test_dedupe_collapses_repeated_active_segments_last_wins():
    from app.upload import _dedupe_bob_records
    from datetime import date
    eff = date(2026, 1, 1)
    records = [
        {"carrier": "UHC", "member_id": "M1", "plan_name": "Plan A",
         "status": "active", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "M2", "plan_name": "Other",
         "status": "active", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "M1", "plan_name": "Plan B",
         "status": "active", "effective_date": eff, "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 2
    m1 = [r for r in out if r["member_id"] == "M1"]
    assert len(m1) == 1
    assert m1[0]["plan_name"] == "Plan B"      # tie on effective date -> last wins
    assert [r["member_id"] for r in out] == ["M1", "M2"]   # original order preserved


def test_dedupe_passes_through_rows_without_member_id():
    from app.upload import _dedupe_bob_records
    records = [
        {"carrier": "UHC", "member_id": None, "full_name": "A"},
        {"carrier": "UHC", "member_id": "", "full_name": "B"},
        {"carrier": "UHC", "member_id": "M9", "full_name": "C"},
    ]
    out = _dedupe_bob_records(records)
    # the two id-less rows are NOT collapsed onto each other
    assert len(out) == 3


def test_dedupe_scopes_by_carrier():
    from app.upload import _dedupe_bob_records
    records = [
        {"carrier": "UHC", "member_id": "X"},
        {"carrier": "Humana", "member_id": "X"},   # same id, different carrier — distinct
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 2


def _bob_rec(carrier, member_id, mbi, **kw):
    base = {"carrier": carrier, "member_id": member_id, "mbi": mbi,
            "first_name": "A", "last_name": "B", "full_name": "A B",
            "plan_name": "P", "plan_type": "MAPD", "effective_date": None,
            "term_date": None, "dob": None, "phone": "", "county": "",
            "agent_id": "", "status": "active"}
    base.update(kw)
    return base


def test_import_row_per_savepoint_isolates_a_failing_row(db_session, app, agency, agent_user):
    """A row whose flush raises (here: a member_id that collides with a DIFFERENT
    agency's committed policy on the global uq_carrier_member) must roll back JUST
    itself via the caller's savepoint and NOT poison the session — the next good
    row still imports. Reproduces the June UHC 500 (a UniqueViolation poisoned the
    session → every later row 500'd with PendingRollbackError)."""
    from app.extensions import db
    from app.models import ImportBatch, Policy
    from app.upload import _import_bob_row
    from datetime import date

    with app.app_context():
        # A pre-existing committed policy on member_id COLLIDE (global unique key).
        db.session.add(Policy(agency_id=999, carrier="UHC", member_id="COLLIDE",
                              mbi="MBIOTHER999", status="active"))
        batch = ImportBatch(agency_id=agency.id, carrier="UHC", filename="f.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()

        good = _bob_rec("UHC", "GOOD1", "MBIGOOD0001")
        # this row's agency-scoped match finds nothing, tries to INSERT (UHC, COLLIDE)
        # → trips the GLOBAL unique constraint → raises on flush.
        bad = _bob_rec("UHC", "COLLIDE", "MBIBAD00001")
        good2 = _bob_rec("UHC", "GOOD2", "MBIGOOD0002")

        for rec in (good, bad, good2):
            try:
                with db.session.begin_nested():
                    _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
            except Exception:
                pass
        db.session.commit()   # MUST NOT raise — session not poisoned

        # both good rows imported under OUR agency; the bad one was isolated
        assert Policy.query.filter_by(agency_id=agency.id, member_id="GOOD1").count() == 1
        assert Policy.query.filter_by(agency_id=agency.id, member_id="GOOD2").count() == 1
        assert Policy.query.filter_by(agency_id=agency.id, member_id="COLLIDE").count() == 0


def test_dedupe_prevents_in_file_duplicate_collision(db_session, app, agency, agent_user):
    """In-file duplicate ACTIVE rows for the same (carrier, member_id) must collapse
    to one BEFORE import so they never hit uq_carrier_member, and the surviving row is
    the chronologically latest active enrollment."""
    from app.extensions import db
    from app.models import ImportBatch, Policy
    from app.upload import _import_bob_row, _dedupe_bob_records
    from datetime import date

    with app.app_context():
        batch = ImportBatch(agency_id=agency.id, carrier="UHC", filename="f.xlsx",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(Policy(agency_id=agency.id, carrier="UHC", member_id="DUP1",
                              mbi="MBIDUP0001", first_name="A", last_name="B",
                              full_name="A B", plan_name="Plan A", status="active"))
        db.session.add(batch); db.session.commit()

        records = [
            _bob_rec("UHC", "DUP1", "MBIDUP0001", plan_name="Plan A",
                     effective_date=date(2024, 1, 1)),
            _bob_rec("UHC", "DUP1", "MBIDUP0001", plan_name="Plan B",
                     effective_date=date(2026, 1, 1)),
        ]
        for rec in _dedupe_bob_records(records):
            with db.session.begin_nested():
                _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
        db.session.commit()   # MUST NOT raise UniqueViolation

        pols = Policy.query.filter_by(agency_id=agency.id, member_id="DUP1").all()
        assert len(pols) == 1                 # collapsed, no collision
        assert pols[0].status == "active"
        assert pols[0].plan_name == "Plan B"  # latest effective date wins


def test_rec_more_current_untermed_beats_real_term():
    """Robbie Belk core: an un-termed (None term) row beats a real-past-termed row.
    Term date is checked before effective date."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2026, 1, 1), "term_date": None}            # current
    kept = {"effective_date": date(2023, 1, 1), "term_date": date(2025, 12, 31)}
    assert _rec_is_more_current(new, kept) is True
    # reverse: a real-past-termed row does NOT replace an un-termed one
    assert _rec_is_more_current(kept, new) is False


def test_rec_more_current_untermed_beats_real_term_even_when_older_effective():
    """Rapid-disenroll: a NEWER enrollment that already termed must NOT beat an OLDER
    still-open policy the member fell back to. Term date wins over effective date."""
    from app.upload import _rec_is_more_current
    from datetime import date
    open_older = {"effective_date": date(2025, 1, 1), "term_date": None}
    termed_newer = {"effective_date": date(2026, 1, 1), "term_date": date(2026, 2, 28)}
    # the older-but-open policy is the survivor
    assert _rec_is_more_current(open_older, termed_newer) is True
    assert _rec_is_more_current(termed_newer, open_older) is False


def test_rec_more_current_both_real_term_later_term_wins():
    """Both rows carry a real term -> the later term date wins; if those tie, the
    later effective date breaks it."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2024, 1, 1), "term_date": date(2026, 12, 31)}
    kept = {"effective_date": date(2024, 1, 1), "term_date": date(2025, 12, 31)}
    assert _rec_is_more_current(new, kept) is True


def test_rec_more_current_term_tie_later_effective_wins():
    """Term dates tie (both un-termed) -> later effective date wins."""
    from app.upload import _rec_is_more_current
    from datetime import date
    new = {"effective_date": date(2026, 1, 1), "term_date": None}
    kept = {"effective_date": date(2023, 1, 1), "term_date": None}
    assert _rec_is_more_current(new, kept) is True
    assert _rec_is_more_current(kept, new) is False


def test_rec_more_current_full_tie_last_wins():
    """Full tie (same term, same effective) -> later-iterated row wins (UHC parity)."""
    from app.upload import _rec_is_more_current
    from datetime import date
    eff = date(2026, 1, 1)
    new = {"effective_date": eff, "term_date": None}
    kept = {"effective_date": eff, "term_date": None}
    assert _rec_is_more_current(new, kept) is True


def test_dedupe_active_and_termed_coexist():
    """Robbie Belk: an ACTIVE current enrollment and a TERMED old enrollment share
    the same (carrier, member_id). They must NOT collapse — both survive so the
    termed row can seed plan-history and the active row owns the policy."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    records = [
        {"carrier": "Aetna", "member_id": "6274", "status": "termed",
         "plan_name": "Value Plus", "effective_date": date(2023, 1, 1),
         "term_date": date(2025, 12, 31)},
        {"carrier": "Aetna", "member_id": "6274", "status": "active",
         "plan_name": "Chronic Care C-SNP", "effective_date": date(2026, 1, 1),
         "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 2
    statuses = sorted(r["status"] for r in out)
    assert statuses == ["active", "termed"]


def test_dedupe_two_active_latest_effective_wins_order_independent():
    """Two ACTIVE rows, same key, different effective dates -> the later-effective
    one is the surviving policy regardless of input order."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    older = {"carrier": "Aetna", "member_id": "M1", "status": "active",
             "plan_name": "Old", "effective_date": date(2023, 1, 1), "term_date": None}
    newer = {"carrier": "Aetna", "member_id": "M1", "status": "active",
             "plan_name": "New", "effective_date": date(2026, 1, 1), "term_date": None}
    for records in ([older, newer], [newer, older]):
        out = _dedupe_bob_records(records)
        survivors = [r for r in out if r["member_id"] == "M1"]
        assert len(survivors) == 1
        assert survivors[0]["plan_name"] == "New"


def test_dedupe_uhc_plan_segments_last_wins_unchanged():
    """UHC plan-segments: multiple ACTIVE rows sharing key AND effective_date ->
    last-in-file wins, exactly as before this change."""
    from app.upload import _dedupe_bob_records
    from datetime import date
    eff = date(2026, 1, 1)
    records = [
        {"carrier": "UHC", "member_id": "U1", "status": "active",
         "plan_name": "Seg A", "effective_date": eff, "term_date": None},
        {"carrier": "UHC", "member_id": "U1", "status": "active",
         "plan_name": "Seg B", "effective_date": eff, "term_date": None},
    ]
    out = _dedupe_bob_records(records)
    survivors = [r for r in out if r["member_id"] == "U1"]
    assert len(survivors) == 1
    assert survivors[0]["plan_name"] == "Seg B"   # last wins


def test_dedupe_passes_through_rows_without_member_id_still():
    from app.upload import _dedupe_bob_records
    records = [
        {"carrier": "UHC", "member_id": None, "full_name": "A", "status": "active"},
        {"carrier": "UHC", "member_id": "", "full_name": "B", "status": "active"},
        {"carrier": "UHC", "member_id": "M9", "full_name": "C", "status": "active"},
    ]
    out = _dedupe_bob_records(records)
    assert len(out) == 3


def test_active_plus_termed_import_keeps_active_policy_and_seeds_history(
        db_session, app, agency, agent_user):
    """Robbie Belk end-to-end: a member with an old TERMED enrollment and a current
    ACTIVE enrollment imports to an ACTIVE policy (latest plan) AND a closed
    plan-history chapter for the old enrollment."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Customer, CustomerAorHistory
    from app.upload import _import_bob_row, _dedupe_bob_records
    from datetime import date

    with app.app_context():
        # Member already exists as a customer (so the termed router acts, not skips).
        db.session.add(Customer(agency_id=agency.id, first_name="Robbie",
                                last_name="Belk", full_name="Robbie Belk",
                                mbi="MBIROBBIE01", primary_agent_id=agent_user.id))
        db.session.add(Policy(agency_id=agency.id, carrier="Aetna", member_id="6274",
                              mbi="MBIROBBIE01", first_name="Robbie", last_name="Belk",
                              full_name="Robbie Belk", plan_name="Value Plus",
                              status="active", effective_date=date(2023, 1, 1)))
        batch = ImportBatch(agency_id=agency.id, carrier="Aetna", filename="f.csv",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()

        records = [
            _bob_rec("Aetna", "6274", "MBIROBBIE01", status="active",
                     plan_name="Chronic Care C-SNP",
                     effective_date=date(2026, 1, 1), term_date=None,
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
            _bob_rec("Aetna", "6274", "MBIROBBIE01", status="termed",
                     plan_name="Value Plus",
                     effective_date=date(2023, 1, 1), term_date=date(2025, 12, 31),
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
        ]
        for rec in _dedupe_bob_records(records):
            with db.session.begin_nested():
                _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
        db.session.commit()

        pols = Policy.query.filter_by(agency_id=agency.id, member_id="6274").all()
        assert len(pols) == 1
        assert pols[0].status == "active"
        assert pols[0].plan_name == "Chronic Care C-SNP"
        assert pols[0].effective_date == date(2026, 1, 1)

        cust = Customer.query.filter_by(mbi="MBIROBBIE01").first()
        hist = CustomerAorHistory.query.filter_by(
            customer_id=cust.id, carrier="Aetna").all()
        closed = [h for h in hist if h.effective_date == date(2023, 1, 1)]
        assert len(closed) == 1
        assert closed[0].plan_name == "Value Plus"
        assert closed[0].end_date == date(2025, 12, 31)


def test_active_plus_termed_import_termed_row_first_still_active(
        db_session, app, agency, agent_user):
    """Order-independence: even when the OLD termed row appears BEFORE the active row
    in the file, the surviving policy is still the current active enrollment — the
    termed-history row must not leave the live policy terminated."""
    from app.extensions import db
    from app.models import ImportBatch, Policy, Customer
    from app.upload import _import_bob_row, _dedupe_bob_records
    from datetime import date

    with app.app_context():
        db.session.add(Customer(agency_id=agency.id, first_name="Robbie",
                                last_name="Belk", full_name="Robbie Belk",
                                mbi="MBIROBBIE02", primary_agent_id=agent_user.id))
        db.session.add(Policy(agency_id=agency.id, carrier="Aetna", member_id="6275",
                              mbi="MBIROBBIE02", first_name="Robbie", last_name="Belk",
                              full_name="Robbie Belk", plan_name="Value Plus",
                              status="active", effective_date=date(2023, 1, 1)))
        batch = ImportBatch(agency_id=agency.id, carrier="Aetna", filename="f.csv",
                            uploaded_by_id=agent_user.id, status="pending")
        db.session.add(batch); db.session.commit()

        records = [
            _bob_rec("Aetna", "6275", "MBIROBBIE02", status="termed",
                     plan_name="Value Plus",
                     effective_date=date(2023, 1, 1), term_date=date(2025, 12, 31),
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
            _bob_rec("Aetna", "6275", "MBIROBBIE02", status="active",
                     plan_name="Chronic Care C-SNP",
                     effective_date=date(2026, 1, 1), term_date=None,
                     first_name="Robbie", last_name="Belk", full_name="Robbie Belk"),
        ]
        for rec in _dedupe_bob_records(records):
            with db.session.begin_nested():
                _import_bob_row(rec, batch, agency.id, agent_user.id, date.today(), [])
        db.session.commit()

        pols = Policy.query.filter_by(agency_id=agency.id, member_id="6275").all()
        assert len(pols) == 1
        assert pols[0].status == "active"
        assert pols[0].plan_name == "Chronic Care C-SNP"
