# Corrected Lane-Aware Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the disabled reissued-MBI override with a lane-aware corrected merge that consolidates a same-person duplicate, keeps the correct current MBI, auto-terms ONLY a superseded primary-medical plan (never a coexisting product), and re-enables the `/admin/customers/duplicates` UI — unblocking Barbara Overcash.

**Architecture:** A new pure `plan_lane()` classifier + a `resolve_primary_medical()` decision function (`app/plan_lane.py`), and a `merge_customers_lane_aware()` wrapper (`app/customers.py`) that resolves the MBI + supersession BEFORE calling the untouched `merge_customers` engine, then terms the superseded primary-medical policy (and closes its AOR chapter) after. The disabled override route is rewired to call it and re-enabled.

**Tech Stack:** Flask, SQLAlchemy (Postgres prod / SQLite tests), pytest.

## Global Constraints

- **`plan_lane()` is a PURE function** — never persisted, never overwrites `plan_type`. Merge-only lens. The specific type (HI vs DVH vs Life) stays intact for filtering.
- **`merge_customers` engine is NOT modified** — its "one non-null MBI" guard stays. The wrapper nulls the stale MBI(s) BEFORE calling it so one MBI remains.
- **Auto-term ONLY when unambiguous:** two active primary-medical policies with **known DIFFERENT contract codes** AND one **strictly-newer effective date** → term the older. Otherwise `needs_review` → term NOTHING.
- **Effective plan_type / contract code:** read from the Policy, and **when blank, fall back to the linked `Plan`** (`policy.plan_type or Plan.plan_type`; `policy.contract_code or Plan.cms_plan_id`). (Grounding: Overcash's Aetna policy has `plan_type=''` but its linked Plan 287 is `pdp` with code `S5601-017`.)
- **Only primary-medical is in scope for supersession.** Medigap / ancillary / other policies always pass through active, untouched.
- **Current MBI** = the current primary-medical plan's MBI **if valid CMS format**; a non-MBI value (a policy number) is never the MBI.
- **Terming a policy closes its open AOR chapter** (`_close_open_aor_on_term`, upload.py:44).
- **Money invariant:** total `PolicyPayment` sum + count unchanged; 0 orphaned payments.
- Same-DOB safety: never merge different DOBs (different-person signal).
- Tests: `python3 -m pytest`. No migration (pure function + existing columns).

---

### Task 1: Lane classifier `plan_lane()`

**Files:**
- Create: `app/plan_lane.py`
- Test: `tests/test_plan_lane.py` (new)

**Interfaces:**
- Consumes: `app.plan_sections.coverage_category(plan_type)` (existing → returns part_c/pdp/medigap/dvh/hospital_indemnity/other).
- Produces: `plan_lane(plan_type) -> str` in {"primary_medical","medigap","ancillary","other"}.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plan_lane.py`:

```python
from app.plan_lane import plan_lane


def test_primary_medical_lane():
    for t in ("mapd", "MAPD", "ma", "dsnp", "csnp", "pdp", "PDP"):
        assert plan_lane(t) == "primary_medical", t


def test_medigap_lane():
    for t in ("medigap", "ms", "MS"):
        assert plan_lane(t) == "medigap", t


def test_ancillary_lane():
    for t in ("dvh", "dental", "hi", "hospital_indemnity", "gtl", "life"):
        assert plan_lane(t) == "ancillary", t


def test_other_lane():
    for t in ("", None, "something_unknown"):
        assert plan_lane(t) == "other", repr(t)
```

- [ ] **Step 2: Run to verify fail**

Run: `python3 -m pytest tests/test_plan_lane.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement**

Create `app/plan_lane.py`:

```python
"""Lane classifier for the corrected lane-aware merge (spec
docs/superpowers/specs/2026-07-24-corrected-lane-aware-merge-design.md).

A plan's LANE decides whether it can coexist with another plan on one person, or
whether a newer plan supersedes it. PURE + on-demand — never persisted, never
overwrites plan_type. The specific plan_type/coverage_category stays intact for
all filtering (HI vs DVH vs Life stay distinguishable).

  primary_medical : MAPD, MA-only, PDP  -> exactly ONE active at a time
  medigap         : Medigap/MS          -> free coexist, never auto-term
  ancillary       : DVH, HI, Life       -> free coexist, never auto-term
  other           : unknown             -> never auto-term
"""
from app.plan_sections import coverage_category

_LANE_OF_CATEGORY = {
    "part_c": "primary_medical",
    "pdp": "primary_medical",
    "medigap": "medigap",
    "dvh": "ancillary",
    "hospital_indemnity": "ancillary",
}


def plan_lane(plan_type):
    """Map a plan_type string to its merge lane. 'life' (not in coverage_category)
    is ancillary; everything unknown is 'other'."""
    pt = (plan_type or "").strip().lower()
    if pt == "life":
        return "ancillary"
    cat = coverage_category(plan_type)
    return _LANE_OF_CATEGORY.get(cat, "other")
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_plan_lane.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/plan_lane.py tests/test_plan_lane.py
git commit -m "feat: plan_lane classifier (primary_medical/medigap/ancillary/other)"
```

---

### Task 2: `resolve_primary_medical()`

**Files:**
- Modify: `app/plan_lane.py`
- Test: `tests/test_plan_lane.py`

**Interfaces:**
- Consumes: `plan_lane` (Task 1); each policy exposes `plan_type`, `contract_code`, `effective_date`, `status`, and an optional linked `Plan` (via `plan` relationship or a resolver — the function takes a small helper to read effective type/code, see below).
- Produces: `resolve_primary_medical(policies, plan_type_of=None, code_of=None) -> dict` with keys `current` (policy|None), `supersede` (list), `needs_review` (bool).

The function must not depend on the DB session shape — callers pass `plan_type_of(policy)` and `code_of(policy)` accessors so it stays unit-testable with plain stub objects. Provide sensible defaults that read `policy.plan_type` / `policy.contract_code`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_plan_lane.py`:

```python
from app.plan_lane import resolve_primary_medical
from datetime import date


class _P:
    """Minimal policy stub."""
    def __init__(self, pid, plan_type, code, eff, status="active"):
        self.id = pid; self.plan_type = plan_type; self.contract_code = code
        self.effective_date = eff; self.status = status


def test_resolve_overcash_supersede():
    # Aetna PDP 2024 (S-code) vs UHC MAPD 2026 (H-code): diff codes, UHC newer.
    aetna = _P(1, "pdp", "S5601-017", date(2024, 1, 1))
    uhc = _P(2, "mapd", "H5253-117", date(2026, 1, 1))
    r = resolve_primary_medical([aetna, uhc])
    assert r["current"] is uhc
    assert r["supersede"] == [aetna]
    assert r["needs_review"] is False


def test_resolve_renewal_same_code_no_term():
    # Same contract code across years = renewal, NOT supersession.
    a = _P(1, "mapd", "H1036-335", date(2025, 1, 1))
    b = _P(2, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True        # same code = can't auto-resolve -> review


def test_resolve_missing_code_needs_review():
    a = _P(1, "mapd", None, date(2025, 1, 1))
    b = _P(2, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True


def test_resolve_eff_tie_needs_review():
    a = _P(1, "mapd", "H1036-335", date(2026, 1, 1))
    b = _P(2, "mapd", "H9999-001", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    assert r["supersede"] == []
    assert r["needs_review"] is True


def test_resolve_single_primary_medical():
    a = _P(1, "mapd", "H1036-335", date(2026, 1, 1))
    r = resolve_primary_medical([a])
    assert r["current"] is a and r["supersede"] == [] and r["needs_review"] is False


def test_resolve_ignores_non_primary_medical():
    # Benson-shape: medigap + dvh -> NO primary-medical -> nothing to resolve.
    mg = _P(1, "ms", "G", date(2025, 9, 1))
    dvh = _P(2, "dvh", None, date(2025, 9, 1))
    r = resolve_primary_medical([mg, dvh])
    assert r["current"] is None and r["supersede"] == [] and r["needs_review"] is False


def test_resolve_only_active():
    a = _P(1, "mapd", "H1036-335", date(2024, 1, 1), status="termed")
    b = _P(2, "mapd", "H9999-001", date(2026, 1, 1))
    r = resolve_primary_medical([a, b])
    # the termed one is out of scope -> only b remains -> single current, no supersede
    assert r["current"] is b and r["supersede"] == [] and r["needs_review"] is False
```

- [ ] **Step 2: Run to verify fail**

Run: `python3 -m pytest tests/test_plan_lane.py -k resolve -v`
Expected: FAIL (`resolve_primary_medical` not defined).

- [ ] **Step 3: Implement**

Add to `app/plan_lane.py`:

```python
def _default_type_of(p):
    return getattr(p, "plan_type", None)


def _default_code_of(p):
    return getattr(p, "contract_code", None)


def resolve_primary_medical(policies, plan_type_of=None, code_of=None):
    """Decide which primary-medical plan is current and which older ones to term.

    Auto-supersede ONLY when unambiguous: two+ active primary-medical policies
    with KNOWN DIFFERENT contract codes AND exactly one strictly-newer effective
    date. Otherwise term nothing and flag needs_review. Medigap/ancillary/other
    are never in scope. Callers may pass plan_type_of/code_of accessors to supply
    the EFFECTIVE type/code (e.g. falling back to the linked Plan when blank)."""
    type_of = plan_type_of or _default_type_of
    code_of = code_of or _default_code_of

    pm = [p for p in policies
          if getattr(p, "status", "active") == "active"
          and plan_lane(type_of(p)) == "primary_medical"]

    if len(pm) <= 1:
        return {"current": pm[0] if pm else None, "supersede": [], "needs_review": False}

    # 2+ primary-medical. Unambiguous only when all codes known + all distinct +
    # a single strict-newest effective date.
    codes = [(code_of(p) or "").strip().upper() for p in pm]
    effs = [getattr(p, "effective_date", None) for p in pm]
    if any(not c for c in codes) or len(set(codes)) != len(codes) or any(e is None for e in effs):
        return {"current": None, "supersede": [], "needs_review": True}

    newest = max(effs)
    newest_holders = [p for p, e in zip(pm, effs) if e == newest]
    if len(newest_holders) != 1:                    # eff tie -> ambiguous
        return {"current": None, "supersede": [], "needs_review": True}

    current = newest_holders[0]
    return {"current": current,
            "supersede": [p for p in pm if p is not current],
            "needs_review": False}
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_plan_lane.py -k resolve -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/plan_lane.py tests/test_plan_lane.py
git commit -m "feat: resolve_primary_medical (unambiguous supersede, else needs_review)"
```

---

### Task 3: `merge_customers_lane_aware()` wrapper

**Files:**
- Modify: `app/customers.py`
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `plan_lane`, `resolve_primary_medical` (Tasks 1-2); `merge_customers` (existing, UNCHANGED); `_close_open_aor_on_term` (import from `app.upload`); the MBI validator (add `is_valid_mbi` locally or import — define it in this task).
- Produces: `merge_customers_lane_aware(keeper_id, loser_ids, agency_id, actor) -> dict` with keys `ok`, `merged`, `current_mbi`, `superseded_policy_ids`, `needs_review`, `error`. `merge_customers` commits internally (via `log_event`), so this wrapper stages ALL its changes (MBI null, supersede-term + AOR close) BEFORE calling the engine — the engine's commit lands everything atomically. No second commit; no separate caller commit needed.

**Effective type/code accessors** (fall back to linked Plan):

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_customer_merge.py` (it has `_client_app`, `_c`, `_policy`, `_stmt`, `_login`). Note `_policy` may need a `contract_code`/`plan_type` — extend the helper inline in the test if needed:

```python
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
```

- [ ] **Step 2: Run to verify fail**

Run: `python3 -m pytest tests/test_customer_merge.py -k lane_merge -v`
Expected: FAIL (`merge_customers_lane_aware` not defined).

- [ ] **Step 3: Implement**

Add to `app/customers.py` (near `merge_customers`). Add the MBI validator + effective accessors + the wrapper:

```python
import re as _re
_MBI_L = "ACDEFGHJKMNPQRTUVWXY"
_MBI_RE = _re.compile(
    r"^[1-9][%(L)s][0-9%(L)s][0-9][%(L)s][0-9%(L)s][0-9][%(L)s][%(L)s][0-9][0-9]$"
    % {"L": _MBI_L})


def _is_valid_mbi(v):
    return bool(v) and bool(_MBI_RE.match(str(v).strip().upper()))


def _eff_type_of(p):
    """Policy plan_type, falling back to the linked Plan's plan_type when blank."""
    t = (p.plan_type or "").strip()
    if t:
        return t
    if p.plan_id:
        from app.models import Plan
        pl = db.session.get(Plan, p.plan_id)
        if pl and pl.plan_type:
            return pl.plan_type
    return ""


def _eff_code_of(p):
    """Policy contract_code, falling back to the linked Plan's cms_plan_id."""
    c = (p.contract_code or "").strip()
    if c:
        return c
    if p.plan_id:
        from app.models import Plan
        pl = db.session.get(Plan, p.plan_id)
        if pl and pl.cms_plan_id:
            return pl.cms_plan_id
    return ""


def merge_customers_lane_aware(keeper_id, loser_ids, agency_id, actor):
    """Lane-aware corrected merge (spec 2026-07-24-corrected-lane-aware-merge).
    Consolidates same-person duplicates: resolves the current MBI + primary-medical
    supersession BEFORE calling the untouched merge_customers engine, then terms the
    superseded primary-medical policy (and closes its AOR chapter) after. Keeps all
    coexisting products (Medigap/ancillary) active. Same-DOB required."""
    from app.plan_lane import resolve_primary_medical
    from app.upload import _close_open_aor_on_term

    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first()
    losers = (Customer.query.filter(Customer.agency_id == agency_id,
                                    Customer.id.in_(loser_ids),
                                    Customer.id != keeper_id).all())
    if not keeper or not losers:
        return {"ok": False, "error": "keeper/losers not found", "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    everyone = [keeper] + losers
    dobs = {c.dob for c in everyone if c.dob is not None}
    if len(dobs) > 1:
        return {"ok": False, "error": "different DOB — not the same person", "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    ids = [c.id for c in everyone]
    policies = Policy.query.filter(Policy.agency_id == agency_id,
                                   Policy.customer_id.in_(ids),
                                   Policy.status == "active").all()
    r = resolve_primary_medical(policies, plan_type_of=_eff_type_of, code_of=_eff_code_of)

    # Current MBI = current primary-medical plan's MBI if valid; else the single
    # valid MBI present across the records.
    current = r["current"]
    current_mbi = None
    if current and _is_valid_mbi(current.member_id):
        current_mbi = current.member_id.strip().upper()
    else:
        valid = {c.mbi.strip().upper() for c in everyone if _is_valid_mbi(c.mbi)}
        if len(valid) == 1:
            current_mbi = next(iter(valid))
        elif len(valid) > 1:
            # two real MBIs + no unambiguous current plan -> refuse (don't guess)
            return {"ok": False, "error": "can't determine current MBI — resolve the "
                    "primary-medical plan first", "merged": 0, "current_mbi": None,
                    "superseded_policy_ids": [], "needs_review": True}

    # Null any customer MBI that differs from the current one (so the engine guard
    # passes with a single MBI). A non-MBI value (policy number) is nulled too.
    for c in everyone:
        cm = (c.mbi or "").strip().upper()
        if cm and cm != current_mbi:
            c.mbi = None
    if keeper.mbi is None and current_mbi:
        keeper.mbi = current_mbi

    # Term the superseded primary-medical policies + close their AOR chapter BEFORE
    # the merge, so it rides the engine's single commit (merge_customers commits
    # internally via log_event; doing the term AFTER would be a second commit whose
    # failure path could falsely report "no changes" while the merge is committed —
    # the exact atomic-ordering bug the shipped override's opus review caught). The
    # AOR chapter is closed on whichever customer currently owns it (the policy may
    # still be on a loser at this point); the merge then re-homes it onto the keeper.
    superseded_ids = []
    if not r["needs_review"] and current is not None:
        term_date = (current.effective_date - _timedelta(days=1)) if current.effective_date else None
        for sp in r["supersede"]:
            p = db.session.get(Policy, sp.id)
            if p and p.status == "active":
                owner = db.session.get(Customer, p.customer_id)
                p.status = "termed"
                p.term_date = term_date
                p.term_reason = "Superseded (merge)"
                if owner:
                    _close_open_aor_on_term(owner, p.carrier, term_date)
                superseded_ids.append(p.id)
    db.session.flush()

    res = merge_customers(keeper_id, loser_ids, agency_id, actor)
    if not res["ok"]:
        db.session.rollback()
        return {"ok": False, "error": res["error"], "merged": 0,
                "current_mbi": None, "superseded_policy_ids": [], "needs_review": False}

    # merge_customers committed internally. No second commit needed.
    return {"ok": True, "merged": res.get("merged", 0), "current_mbi": current_mbi,
            "superseded_policy_ids": superseded_ids, "needs_review": r["needs_review"],
            "error": None}
```

Add `from datetime import timedelta as _timedelta` to the imports at the top of `app/customers.py` (check it isn't already imported; `datetime`/`date` are imported at line 11).

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m pytest tests/test_customer_merge.py -k lane_merge -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full merge suite (engine untouched)**

Run: `python3 -m pytest tests/test_customer_merge.py tests/test_dedup.py -q`
Expected: all pass (existing `merge_customers` guard tests green).

- [ ] **Step 6: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: merge_customers_lane_aware (resolve MBI + supersession, term only primary-medical)"
```

---

### Task 4: Rewire the route + re-enable + broaden the gate

**Files:**
- Modify: `app/customers.py` — `customer_merge_reissued_mbi` route + `REISSUED_MBI_MERGE_ENABLED` + `customer_duplicates` cluster dict
- Modify: `app/dedup.py` — broaden the gate helper (or add a new one)
- Modify: `app/templates/customer_duplicates.html` — panel copy + preview
- Test: `tests/test_customer_merge.py`, `tests/test_duplicates_page_renders.py`

**Interfaces:**
- Consumes: `merge_customers_lane_aware` (Task 3).
- Produces: the route calls the lane-aware merge; the panel is offered on any same-DOB conflict cluster; `REISSUED_MBI_MERGE_ENABLED = True`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_customer_merge.py` (route-level, Overcash shape via the client):

```python
def test_route_lane_merge_overcash():
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="1X88VQ0CP30")
        loser = _c(aid, full_name="Barbara Overcash", dob=_date(1940, 10, 24), mbi="2WA7KC0TM50")
        _pol(aid, keeper.id, "UHC", "1X88VQ0CP30", "mapd", "H5253-117", _date(2026, 1, 1))
        _pol(aid, loser.id, "Aetna", "2WA7KC0TM50", "pdp", "S5601-017", _date(2024, 1, 1))
        db.session.commit()
        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id})
        assert resp.status_code in (302, 303)
        assert db.session.get(Customer, loser.id) is None          # merged
        k = db.session.get(Customer, keeper.id)
        assert k.mbi == "1X88VQ0CP30"
        assert {p.status for p in Policy.query.filter_by(customer_id=keeper.id, carrier="Aetna")} == {"termed"}
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()
```

And update `tests/test_duplicates_page_renders.py`: the reissued-panel-hidden test must now assert the panel is SHOWN for a same-DOB conflict cluster (rename `test_reissued_override_panel_hidden_while_disabled` → `test_lane_merge_panel_shown_for_conflict` asserting `b"merge-reissued-mbi" in resp.data`).

- [ ] **Step 2: Run to verify fail**

Run: `python3 -m pytest tests/test_customer_merge.py -k route_lane -v`
Expected: FAIL — route still disabled (flashes "temporarily disabled").

- [ ] **Step 3: Rewire the route + flip the flag**

In `app/customers.py`: set `REISSUED_MBI_MERGE_ENABLED = True`. Replace the body of `customer_merge_reissued_mbi` (from `stale_mbi = loser.mbi` through the final return) so it calls the lane-aware merge:

```python
    # (keep the top: flag check, read keeper_id/loser_id, load keeper+loser,
    #  same-DOB gate re-check)
    res = merge_customers_lane_aware(keeper.id, [loser.id], agency_id, current_user)
    if not res["ok"]:
        db.session.rollback()
        flash(f"Merge blocked: {res['error']}.", "error")
        return redirect(url_for("customers.customer_duplicates"))
    if res["needs_review"]:
        flash(f"Merged {keeper.display_name}. Two primary-medical plans couldn't be "
              "auto-resolved — review which is current on the profile.", "info")
    else:
        n = len(res["superseded_policy_ids"])
        flash(f"Merged into {keeper.display_name}." + (f" Superseded {n} plan(s)." if n else ""),
              "success")
    return redirect(url_for("customers.customer_profile", customer_id=keeper.id))
```

Update the server-side gate: the route currently re-validates `is_reissued_mbi_candidate` (2 records, same DOB, diff MBI). Broaden to a same-DOB check (allow same-MBI-or-diff-MBI, but refuse different DOB). Replace the `is_reissued_mbi_candidate([keeper, loser])` check with:

```python
    if keeper.dob and loser.dob and keeper.dob != loser.dob:
        flash("These records have different DOBs — not the same person.", "error")
        return redirect(url_for("customers.customer_duplicates"))
```

- [ ] **Step 4: Broaden the UI gate flag + panel**

In `app/customers.py` `customer_duplicates`, the cluster dict currently sets `"reissued_candidate": (REISSUED_MBI_MERGE_ENABLED and is_reissued_mbi_candidate(rows))`. Broaden: offer on any `conflict` cluster of a same-person shape. Add a helper `is_lane_merge_candidate(rows)` in `app/dedup.py`:

```python
def is_lane_merge_candidate(rows):
    """Offer the lane-aware merge on a same-DOB pair (2 records, both with a DOB,
    same DOB). Covers reissue, switcher, AND coexistence uniformly. Different DOB =
    different person = not a candidate."""
    if len(rows) != 2:
        return False
    a, b = rows
    if a.dob is None or b.dob is None:
        return False
    return a.dob == b.dob
```

Set the cluster dict flag to `(REISSUED_MBI_MERGE_ENABLED and is_lane_merge_candidate(rows))` (import it alongside the others).

In `app/templates/customer_duplicates.html`, update the panel heading from "Reissued MBI? Reconcile these two records" to "Same person? Reconcile these records" and the help text to describe: keeps the current MBI, terms only a superseded primary-medical plan, keeps coexisting products. (Keep the radio for choosing keeper + the confirm checkbox + `merge-reissued-mbi` form action.)

- [ ] **Step 5: Run to verify pass**

Run: `python3 -m pytest tests/test_customer_merge.py tests/test_duplicates_page_renders.py -k "route_lane or lane_merge_panel" -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/customers.py app/dedup.py app/templates/customer_duplicates.html tests/test_customer_merge.py tests/test_duplicates_page_renders.py
git commit -m "feat: re-enable merge UI with lane-aware merge; broaden gate to same-DOB conflicts"
```

---

### Task 5: Full-suite verification

**Files:** none.

- [ ] **Step 1: Full suite**

Run: `python3 -m pytest -q`
Expected: all pass (prior total + ~15 new).

- [ ] **Step 2: Confirm the engine is untouched**

Run: `git diff main -- app/customers.py | grep -nE "^\-" | grep -v "^---"`
Expected: the only removed lines are inside `customer_merge_reissued_mbi` (the old override body) + the `REISSUED_MBI_MERGE_ENABLED = False` line + the cluster-dict flag line — NOT inside `merge_customers`.

- [ ] **Step 3: Commit (allow-empty marker)**

```bash
git commit --allow-empty -m "chore: corrected lane-aware merge — verification"
```

---

## Self-Review

**Spec coverage:**
- §1 plan_lane → Task 1. ✓
- §2 resolve_primary_medical (unambiguous supersede else needs_review) → Task 2. ✓
- §3 wrapper (resolve MBI → null stale → engine → term superseded + close AOR) → Task 3. ✓
- §4 UI re-enable + broadened gate + panel copy → Task 4. ✓
- §5 tests + money invariant + engine-untouched → Tasks 1-5. ✓
- Effective type/code fallback to linked Plan (Overcash blank plan_type) → Task 3 `_eff_type_of`/`_eff_code_of`. ✓
- Out-of-scope (manual Medigap term, book-wide audit, import reuse, external-primary, MBI history) → correctly not built. ✓

**Placeholder scan:** none — every step has complete code + expected output. ✓

**Type consistency:** `plan_lane(str)->str` (T1) used in T2/T3. `resolve_primary_medical(policies, plan_type_of=, code_of=)->{current,supersede,needs_review}` (T2) consumed in T3. `merge_customers_lane_aware(keeper_id, loser_ids, agency_id, actor)->{ok,merged,current_mbi,superseded_policy_ids,needs_review,error}` (T3) consumed by the route (T4). `is_lane_merge_candidate(rows)->bool` (T4). `_close_open_aor_on_term(customer, carrier, term_date)` matches upload.py:44. `Policy.contract_code` / `Plan.cms_plan_id` / `Plan.plan_type` match models.py. ✓

**Note for executor:** money/identity path — after the suite is green, do opus whole-branch review + real-Postgres verify + DB backup before deploy. No migration. Deploy is human-gated; the rollout (flip already done in code; apply to Overcash live) happens after review.
