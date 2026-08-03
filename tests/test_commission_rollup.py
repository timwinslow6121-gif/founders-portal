"""
tests/test_commission_rollup.py

Retired-agent commission rollup: Cyndi Mortimer and Donald Long are no longer
active agents. Their Aetna and UHC business rolls up to Brian Freeman at his
50% rate. Only Aetna + UHC; only these two agents. Everything else passes
through unchanged.

See app/commission/rollup.py.
"""
import pytest


# --- pure helper: name rewrite, carrier-scoped ----------------------------

def test_donald_long_aetna_rolls_to_brian():
    from app.commission.rollup import apply_rollup
    assert apply_rollup("Long, Donald", "Aetna") == "Brian Freeman"
    assert apply_rollup("LONG, DONALD", "Aetna") == "Brian Freeman"
    assert apply_rollup("Donald Long", "Aetna") == "Brian Freeman"


def test_donald_long_uhc_rolls_to_brian():
    from app.commission.rollup import apply_rollup
    assert apply_rollup("Long, Donald", "UHC") == "Brian Freeman"


def test_cyndi_mortimer_rolls_to_brian_on_both_carriers():
    """Her LEGAL name on the carrier files is 'MORTIMER, CYNTHIA WALKUP' (NOT
    'Cyndi') — the real-file form must roll up."""
    from app.commission.rollup import apply_rollup
    assert apply_rollup("MORTIMER, CYNTHIA WALKUP", "Aetna") == "Brian Freeman"
    assert apply_rollup("MORTIMER, CYNTHIA WALKUP", "UHC") == "Brian Freeman"
    assert apply_rollup("Cynthia Mortimer", "UHC") == "Brian Freeman"


def test_rollup_is_scoped_to_aetna_and_uhc_only():
    """Devoted/BCBS/Humana retired-agent rows are NOT rolled up (no business there
    per AJ). The name passes through unchanged."""
    from app.commission.rollup import apply_rollup
    assert apply_rollup("Long, Donald", "Devoted") == "Long, Donald"
    assert apply_rollup("MORTIMER, CYNTHIA WALKUP", "BCBS") == "MORTIMER, CYNTHIA WALKUP"


def test_active_agents_pass_through_unchanged():
    from app.commission.rollup import apply_rollup
    assert apply_rollup("Foster, Christopher", "Aetna") == "Foster, Christopher"
    assert apply_rollup("Freeman, Brian", "Aetna") == "Freeman, Brian"
    assert apply_rollup("Long, Rebekah", "Aetna") == "Long, Rebekah"  # NOT Donald!


def test_rebekah_long_not_confused_with_donald_long():
    """The two Longs must stay distinct — only Donald rolls up."""
    from app.commission.rollup import apply_rollup
    assert apply_rollup("Long, Rebekah", "Aetna") == "Long, Rebekah"
    assert apply_rollup("Rebekah Long", "UHC") == "Rebekah Long"


def test_empty_and_none_pass_through():
    from app.commission.rollup import apply_rollup
    assert apply_rollup("", "Aetna") == ""
    assert apply_rollup(None, "Aetna") in (None, "")


# --- integration: rollup flows through the resolver + split-rate seams -----

def _make_brian(db, agency, *, aetna_rate=0.50, uhc_rate=0.50):
    from app.models import User, AgentCarrierContract
    brian = User(email="brian@test.com", name="Brian Freeman", is_admin=False,
                 agency_id=agency.id)
    db.session.add(brian)
    db.session.flush()
    for carrier, rate in (("Aetna", aetna_rate), ("UHC", uhc_rate)):
        db.session.add(AgentCarrierContract(
            agency_id=agency.id, agent_id=brian.id, carrier=carrier,
            is_active=True, split_rate=rate))
    db.session.commit()
    return brian


def test_donald_long_resolves_to_brian_via_match_seam(db_session, app, agency):
    """The retired-agent name must resolve to Brian's user id through the same
    _match_agent_name path the ledger uses for attribution."""
    from app.extensions import db
    from app.commission.routes import _match_agent_name
    from app.commission.rollup import apply_rollup

    with app.app_context():
        brian = _make_brian(db, agency)
        # Don is NOT a portal user; only the rollup makes him resolvable.
        assert _match_agent_name("Long, Donald") is None
        assert _match_agent_name(apply_rollup("Long, Donald", "Aetna")) == brian.id


def test_rolled_up_name_finds_brians_aetna_050_contract(db_session, app, agency):
    """After rollup, the resolved agent's Aetna contract carries the 0.50 rate —
    the value the split-rate seam will read for Don's Aetna rows. (Tests the data
    path without Flask-Login's request-scoped current_user.)"""
    from app.extensions import db
    from app.models import AgentCarrierContract
    from app.commission.routes import _match_agent_name
    from app.commission.rollup import apply_rollup

    with app.app_context():
        brian = _make_brian(db, agency, aetna_rate=0.50)
        agent_id = _match_agent_name(apply_rollup("Long, Donald", "Aetna"))
        contract = AgentCarrierContract.query.filter_by(
            agent_id=agent_id, carrier="Aetna", is_active=True).first()
        assert contract is not None and contract.split_rate == 0.50

        # Devoted is NOT a rollup carrier: Don stays unresolvable (no Brian
        # Devoted contract, no rollup), so the seam can't pull Brian's 0.50.
        assert _match_agent_name(apply_rollup("Long, Donald", "Devoted")) is None


def test_rollup_covers_short_name_variants():
    """A carrier writing the familiar form must still roll up. A miss here is
    SILENT: the name falls through to the 0.55 agency fallback and pays the wrong
    amount with no error — the failure mode behind Don Long's original -$18."""
    from app.commission.rollup import apply_rollup
    for raw in ("MORTIMER, CYNDI", "Cyndi Mortimer", "MORTIMER, CYNTHIA WALKUP",
                "LONG, DON", "Don Long", "LONG, DONALD"):
        for carrier in ("UHC", "Aetna"):
            assert apply_rollup(raw, carrier) == "Brian Freeman", (raw, carrier)


def test_rollup_leaves_active_agents_and_other_carriers_alone():
    """Regression guard: Rebekah Long normalizes to 'rebekah long' and must never
    be captured by the 'long' family; and the rollup is Aetna/UHC ONLY."""
    from app.commission.rollup import apply_rollup
    for carrier in ("UHC", "Aetna", "Humana", "BCBS"):
        assert apply_rollup("LONG, REBEKAH", carrier) == "LONG, REBEKAH"
    for carrier in ("Humana", "BCBS", "Devoted", "Healthspring", "Wellabe"):
        assert apply_rollup("MORTIMER, CYNDI", carrier) == "MORTIMER, CYNDI"
        assert apply_rollup("LONG, DONALD", carrier) == "LONG, DONALD"
