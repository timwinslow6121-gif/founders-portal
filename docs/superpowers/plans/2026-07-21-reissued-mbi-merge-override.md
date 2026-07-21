# Reissued-MBI Merge Override Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin merge two customer records that are the same person under a CMS-reissued MBI (same DOB, different MBI), directly from the `/admin/customers/duplicates` UI, instead of running a one-off script.

**Architecture:** A narrow, admin-only override route reproduces the proven script sequence server-side — null the stale MBI on the loser, call the existing `merge_customers` engine (untouched), then term the policy keyed to the stale MBI. A `dedup.py` gate helper decides which conflict clusters are reissued-MBI candidates; the duplicates template renders an override sub-form only for those.

**Tech Stack:** Flask, SQLAlchemy (Postgres in prod, SQLite in tests), Jinja2, pytest.

## Global Constraints

- **Merge engine is NOT modified.** `merge_customers` (`app/customers.py`) keeps its "one non-null MBI only" contradiction guard exactly as-is. The override works by nulling the stale MBI *before* calling it.
- **Admin-only.** Both the route and the UI panel are gated `@_admin_required` / admin-visible; the existing duplicates page is already admin-only.
- **Gate = exactly 2 records, same non-null DOB, differing non-null MBIs.** No other shape qualifies (different DOB, any null DOB/MBI, >2 records all rejected). Server re-validates — never trusts the form.
- **Agency-scoped.** Every Customer/Policy query filters `agency_id`. Never use `current_user` inside engine helpers — pass `agency_id` explicitly (matches codebase rule).
- **Money is not touched.** The route moves policies/payments (via the merge engine) and terms one policy's `status`; it never changes any commission amount.
- **Term rule:** term exactly the moved policy whose `member_id == stale_mbi`; idempotent (skip if already `termed`); no-op if none found.
- Tests: `python3 -m pytest -q`. Follow existing fixture patterns in `tests/test_dedup.py` (helper) and `tests/test_customer_merge.py` / `tests/test_duplicates_page_renders.py` (route + login).

---

### Task 1: Gate helper `is_reissued_mbi_candidate`

**Files:**
- Modify: `app/dedup.py` (add function near `cluster_signal`, ~line 58)
- Test: `tests/test_dedup.py`

**Interfaces:**
- Produces: `is_reissued_mbi_candidate(rows) -> bool` where `rows` is a list of `Customer` objects (a cluster's members). True only for the reissued-MBI shape.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dedup.py` (it already imports `db`, `Customer`, `Agency`, `date`, and has `_cust`):

```python
from app.dedup import is_reissued_mbi_candidate


def test_reissued_candidate_true_same_dob_diff_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, first_name="Milton", last_name="Frazier",
                  full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, first_name="Milton", last_name="Frazier",
                  full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is True


def test_reissued_candidate_false_diff_dob(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1961, 9, 9), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_null_dob(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=None, mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="6RQ6RJ6RV66")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_null_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi=None)
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_same_mbi(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="8U39K22PT26")
        assert is_reissued_mbi_candidate([a, b]) is False


def test_reissued_candidate_false_three_records(app, db_session):
    with app.app_context():
        ag = Agency(name="T"); db.session.add(ag); db.session.flush()
        a = _cust(ag.id, dob=date(1950, 2, 3), mbi="AAA")
        b = _cust(ag.id, dob=date(1950, 2, 3), mbi="BBB")
        c = _cust(ag.id, dob=date(1950, 2, 3), mbi="CCC")
        assert is_reissued_mbi_candidate([a, b, c]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_dedup.py -k reissued -v`
Expected: FAIL with `ImportError` / `cannot import name 'is_reissued_mbi_candidate'`.

- [ ] **Step 3: Write the implementation**

Add to `app/dedup.py` (right after `cluster_signal`, before `count_no_mbi_clusters`):

```python
def is_reissued_mbi_candidate(rows):
    """True only for the exact CMS-reissued-MBI shape: exactly two records,
    both with a non-null DOB that is EQUAL, and both with a non-null MBI that
    DIFFERS. Everything else (different DOB, any null DOB/MBI, >2 rows, same
    MBI) is False — those stay hard-blocked. This is the gate for the
    reissued-MBI merge override; it structurally excludes different-person and
    coexistence clusters."""
    if len(rows) != 2:
        return False
    a, b = rows
    if a.dob is None or b.dob is None or a.dob != b.dob:
        return False
    if not a.mbi or not b.mbi or a.mbi == b.mbi:
        return False
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_dedup.py -k reissued -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add app/dedup.py tests/test_dedup.py
git commit -m "feat: is_reissued_mbi_candidate gate (2 records, same DOB, diff MBI)"
```

---

### Task 2: Override route `customer_merge_reissued_mbi`

**Files:**
- Modify: `app/customers.py` (add route after `customer_merge`, ~line 861)
- Test: `tests/test_customer_merge.py`

**Interfaces:**
- Consumes: `is_reissued_mbi_candidate` (Task 1); `merge_customers(keeper_id, loser_ids, agency_id, actor)` (existing); `log_event(action, *, category, detail=...)` (existing, imported at `app/customers.py:20`).
- Produces: `POST /admin/customers/merge-reissued-mbi` route (endpoint `customers.customer_merge_reissued_mbi`) reading form fields `keeper_id` (int, the record whose MBI stays current) and `loser_id` (int, the record whose MBI is nulled).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_customer_merge.py` (it imports `db`, models, `merge_customers`, `date`; add the route + client imports). Use the `_agency_user`, `_c`, `_stmt` helpers already in that file plus a small login helper:

```python
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


def test_reissued_merge_keeps_current_mbi_terms_stale_policy():
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, first_name="Milton", last_name="Frazier",
                    full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="CURR123")
        loser = _c(aid, first_name="Milton", last_name="Frazier",
                   full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="STALE99")
        _policy(aid, keeper.id, "UHC", "CURR123")          # keeper's live policy
        _policy(aid, loser.id, "UHC", "STALE99")           # stale-keyed policy → should term
        db.session.commit()

        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id},
                           follow_redirects=False)
        assert resp.status_code in (302, 303)

        # loser gone, keeper keeps the current MBI
        assert db.session.get(Customer, loser.id) is None
        k = db.session.get(Customer, keeper.id)
        assert k.mbi == "CURR123"

        # stale-keyed policy termed; live policy untouched
        pols = Policy.query.filter_by(customer_id=keeper.id).all()
        by_mid = {p.member_id: p.status for p in pols}
        assert by_mid["STALE99"] == "termed"
        assert by_mid["CURR123"] == "active"
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


def test_reissued_merge_idempotent_when_stale_already_termed():
    app, client, aid, admin, ctx = _client_app()
    try:
        keeper = _c(aid, full_name="Z Z", dob=date(1950, 2, 3), mbi="CURR")
        loser = _c(aid, full_name="Z Z", dob=date(1950, 2, 3), mbi="STALE")
        _policy(aid, loser.id, "UHC", "STALE", status="termed")  # already termed
        db.session.commit()
        resp = client.post("/admin/customers/merge-reissued-mbi",
                           data={"keeper_id": keeper.id, "loser_id": loser.id})
        assert resp.status_code in (302, 303)
        assert db.session.get(Customer, loser.id) is None
        p = Policy.query.filter_by(customer_id=keeper.id, member_id="STALE").first()
        assert p.status == "termed"
    finally:
        db.session.remove(); db.drop_all(); ctx.pop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_customer_merge.py -k reissued -v`
Expected: FAIL — 404 on the route (endpoint not registered) so the assertions fail.

- [ ] **Step 3: Write the route**

Add to `app/customers.py` immediately after `customer_merge` (ends ~line 861). `is_reissued_mbi_candidate` must be imported — add it to the existing `from app.dedup import ...` usage (there is a local import at line 816; add a module-level import at the top of the merge section or import inline in the route):

```python
@customers_bp.route("/admin/customers/merge-reissued-mbi", methods=["POST"])
@login_required
@_admin_required
def customer_merge_reissued_mbi():
    """Reconcile two records that are the SAME person under a CMS-reissued MBI.
    Gate: exactly 2 records, same non-null DOB, differing non-null MBIs (re-validated
    server-side). Keeps the keeper's (current) MBI, nulls the loser's stale MBI, merges
    via the engine, then terms the policy keyed to the stale MBI. Admin-only."""
    from app.dedup import is_reissued_mbi_candidate
    agency_id = current_user.agency_id
    keeper_id = request.form.get("keeper_id", type=int)
    loser_id = request.form.get("loser_id", type=int)
    if not keeper_id or not loser_id or keeper_id == loser_id:
        flash("Invalid reissued-MBI merge request.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    keeper = Customer.query.filter_by(id=keeper_id, agency_id=agency_id).first_or_404()
    loser = Customer.query.filter_by(id=loser_id, agency_id=agency_id).first_or_404()

    # Re-validate the gate server-side — never trust the form.
    if not is_reissued_mbi_candidate([keeper, loser]):
        flash("These records are not a reissued-MBI pair (need same DOB, different MBI).",
              "error")
        return redirect(url_for("customers.customer_duplicates"))

    stale_mbi = loser.mbi

    # 1) Release the stale MBI so the merge engine's one-MBI guard passes.
    loser.mbi = None
    db.session.flush()

    # 2) Merge the loser into the keeper (engine unchanged; moves policies/payments/AOR).
    res = merge_customers(keeper.id, [loser.id], agency_id, current_user)
    if not res["ok"]:
        db.session.rollback()
        flash(f"Merge blocked: {res['error']}.", "error")
        return redirect(url_for("customers.customer_duplicates"))

    # 3) Term the (now moved) policy keyed to the stale MBI. Idempotent.
    termed_policy_id = None
    stale_policy = (Policy.query
                    .filter_by(agency_id=agency_id, customer_id=keeper.id,
                               member_id=stale_mbi)
                    .first())
    if stale_policy is not None and stale_policy.status != "termed":
        stale_policy.status = "termed"
        termed_policy_id = stale_policy.id

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"reissued-MBI merge commit failed: {e}")
        flash("Merge could not be completed (database conflict). No changes were made.",
              "error")
        return redirect(url_for("customers.customer_duplicates"))

    log_event("customer_merge_reissued_mbi", category="admin",
              detail=(f"keeper={keeper.id} loser={loser_id} stale_mbi={stale_mbi} "
                      f"termed_policy={termed_policy_id}"),
              customer_id=keeper.id)
    flash(f"Reconciled reissued-MBI duplicate into {keeper.display_name}.", "success")
    return redirect(url_for("customers.customer_profile", customer_id=keeper.id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_customer_merge.py -k reissued -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full merge + dedup suites (no regressions)**

Run: `python3 -m pytest tests/test_customer_merge.py tests/test_dedup.py -q`
Expected: all pass (existing `merge_customers` guard tests still green — engine untouched).

- [ ] **Step 6: Commit**

```bash
git add app/customers.py tests/test_customer_merge.py
git commit -m "feat: reissued-MBI merge override route (null stale MBI, merge, term stale policy)"
```

---

### Task 3: Surface the candidate flag + override sub-form in the UI

**Files:**
- Modify: `app/customers.py` — `customer_duplicates()` cluster dict (~line 827)
- Modify: `app/templates/customer_duplicates.html` — conflict branch (~lines 76–124)
- Test: `tests/test_duplicates_page_renders.py`

**Interfaces:**
- Consumes: `is_reissued_mbi_candidate` (Task 1); the override endpoint `customers.customer_merge_reissued_mbi` (Task 2).
- Produces: each `no_mbi_clusters` dict gains `"reissued_candidate": bool`; the template renders the override panel when a `conflict` cluster is a candidate.

- [ ] **Step 1: Write the failing render test**

Add to `tests/test_duplicates_page_renders.py` (reuse its `ctx` fixture + `_login`):

```python
def test_reissued_conflict_cluster_shows_override(ctx):
    from datetime import date
    app, agency_id, admin = ctx
    # Same name + same DOB + different MBI => a `conflict` cluster that IS a
    # reissued-MBI candidate → the override panel must render.
    db.session.add(Customer(agency_id=agency_id, first_name="Milton", last_name="Frazier",
                            full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="CURR123"))
    db.session.add(Customer(agency_id=agency_id, first_name="Milton", last_name="Frazier",
                            full_name="Milton Frazier", dob=date(1950, 2, 3), mbi="STALE99"))
    db.session.commit()
    client = app.test_client(); _login(client, admin)
    resp = client.get("/admin/customers/duplicates")
    assert resp.status_code == 200
    assert b"merge-reissued-mbi" in resp.data       # the override form action is present
    assert b"Reissued MBI" in resp.data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_duplicates_page_renders.py -k reissued -v`
Expected: FAIL — `merge-reissued-mbi` / `Reissued MBI` not in the page.

- [ ] **Step 3: Add the flag in the route**

In `app/customers.py`, in `customer_duplicates()` where each cluster dict is built (~line 827), import the helper and add the flag. The `find_no_mbi_clusters` import is already local at line 816 — extend it:

```python
    from app.dedup import find_no_mbi_clusters, is_reissued_mbi_candidate
    raw_clusters = find_no_mbi_clusters(current_user.agency_id)
    no_mbi_clusters = []
    for cl in raw_clusters:
        rows = (Customer.query
                .filter(Customer.agency_id == current_user.agency_id,
                        Customer.id.in_(cl.member_ids))
                .all())
        if not rows:
            continue
        keeper = next((r for r in rows if r.id == cl.keeper_id), rows[0])
        no_mbi_clusters.append({
            "signal": cl.signal,
            "keeper": keeper,
            "reissued_candidate": is_reissued_mbi_candidate(rows),
            "rows": [_cluster_row_context(r, current_user.agency_id) for r in rows],
        })
```

- [ ] **Step 4: Add the override panel in the template**

In `app/templates/customer_duplicates.html`, replace the `{% if cl.signal == 'conflict' %}` block (the red "merge blocked" `<p>`, ~lines 76–80) with a branch: if it's a reissued candidate, render the override form; else keep today's blocked message. Put the override form OUTSIDE the existing `customer_merge` form (it posts to a different endpoint).

Replace lines 76–80:

```jinja
  {% if cl.signal == 'conflict' %}
    <p style="color: #c0392b; font-size: 13px; margin: 0 0 12px;">
      Different DOB or MBI values in this group — review manually; merge blocked.
    </p>
  {% endif %}
```

with:

```jinja
  {% if cl.signal == 'conflict' and cl.reissued_candidate %}
    <div style="border: 1px solid var(--gold); border-radius: 10px; padding: 14px 16px; margin: 0 0 14px;">
      <p style="color: var(--ivory); font-weight: 600; margin: 0 0 4px;">Reissued MBI? Reconcile these two records</p>
      <p style="color: var(--slate); font-size: 12px; margin: 0 0 10px;">
        Same DOB, different MBI — the mark of a CMS-reissued MBI on one person. Pick the CURRENT MBI
        (the record with the live policy), confirm it's the same person, then merge. The stale MBI's
        policy is termed automatically.
      </p>
      <form method="post" action="{{ url_for('customers.customer_merge_reissued_mbi') }}">
        {% set r0 = cl.rows[0] %}
        {% set r1 = cl.rows[1] %}
        {% for row in cl.rows %}
          {% set other = r1 if row.customer.id == r0.customer.id else r0 %}
          <label style="display:flex; align-items:center; gap:8px; color: var(--ivory); font-size: 13px; padding: 4px 0; cursor:pointer;">
            <input type="radio" name="keeper_id" value="{{ row.customer.id }}"
                   data-loser="{{ other.customer.id }}" required
                   onclick="document.getElementById('rmbi-loser-{{ cl.keeper.id }}').value = this.dataset.loser;">
            Keep <strong>MBI {{ row.mbi }}</strong> as current
            <span style="color: var(--slate); font-size: 12px;">
              — {{ row.customer.display_name }} · DOB {{ row.dob or '—' }}
              · {{ row.policy_count }} {{ 'policy' if row.policy_count == 1 else 'policies' }}{% if row.carriers %} ({{ row.carriers | join(', ') }}){% endif %}
            </span>
          </label>
        {% endfor %}
        <input type="hidden" name="loser_id" id="rmbi-loser-{{ cl.keeper.id }}" value="">
        <label style="display:flex; align-items:center; gap:8px; color: var(--ivory); font-size: 13px; margin: 8px 0 10px; cursor:pointer;">
          <input type="checkbox" required>
          I confirm this is the same person and CMS reissued their MBI
        </label>
        <button type="submit" class="btn-primary" style="font-size: 13px; padding: 7px 18px;">
          Merge (reissued MBI)
        </button>
      </form>
    </div>
  {% elif cl.signal == 'conflict' %}
    <p style="color: #c0392b; font-size: 13px; margin: 0 0 12px;">
      Different DOB or MBI values in this group — review manually; merge blocked.
    </p>
  {% endif %}
```

(The main `customer_merge` form below still renders its blocked/disabled state for the conflict cluster — that's fine; the override form is the reissued-specific path. The `id="rmbi-loser-<keeper.id>"` is unique per card.)

- [ ] **Step 5: Run the render test to verify it passes**

Run: `python3 -m pytest tests/test_duplicates_page_renders.py -k reissued -v`
Expected: PASS.

- [ ] **Step 6: Verify a non-reissued conflict still renders blocked (regression)**

Run: `python3 -m pytest tests/test_duplicates_page_renders.py -q`
Expected: all pass (existing render tests green — a different-DOB conflict shows no override form).

- [ ] **Step 7: Commit**

```bash
git add app/customers.py app/templates/customer_duplicates.html tests/test_duplicates_page_renders.py
git commit -m "feat: reissued-MBI override sub-form on conflict-cluster cards"
```

---

### Task 4: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `python3 -m pytest -q`
Expected: all pass; the count is the prior suite total plus the ~10 new tests (6 gate + 3 route + 1 render).

- [ ] **Step 2: Confirm the merge engine is unchanged**

Run: `git diff main -- app/customers.py | grep -n "def merge_customers" -A2`
Expected: the `merge_customers` signature + guard body appear only as context (no edits inside the function) — the diff should show only the NEW route added after `customer_merge`.

- [ ] **Step 3: Commit any final cleanup (if needed)**

```bash
git add -A && git commit -m "chore: reissued-MBI override — final verification" --allow-empty
```

---

## Self-Review

**Spec coverage:**
- Section 1 (gate) → Task 1. ✓
- Section 2 (card UI: radio keep-MBI, confirm checkbox, merge button) → Task 3. ✓
- Section 3 (override route: gate re-check → null stale → merge → term stale policy → audit → commit) → Task 2. ✓
- Section 4 (testing: gate cases, route merge/refuse/idempotent, regression) → Tasks 1–4. ✓
- Out-of-scope items (old merge path, 3-way, switcher pass, auto-detect MBI) → correctly not built. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every command has expected output. ✓

**Type consistency:** `is_reissued_mbi_candidate(rows)->bool` used identically in Tasks 1/2/3. Form fields `keeper_id`/`loser_id` defined in Task 2 route and produced by Task 3 template (radio sets `keeper_id`; JS mirrors the other id into hidden `loser_id`). `merge_customers(keeper_id, loser_ids, agency_id, actor)` matches the existing signature. `Policy.status`/`Policy.member_id` match models.py. `log_event(action, *, category, detail=, customer_id=)` matches app/audit.py. ✓

**Note for executor:** deploy is human-gated (money/identity path) — after the suite is green, do opus whole-branch review + real-Postgres verify + DB backup before any live use, per CLAUDE.md protocol. No migration (no schema change).
