# Ledger Customer Back-Link Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `persist_line_items` so every commission ledger row links to its Customer — resolving 537 of the 641 currently-unlinked rows and preventing a re-upload from ever erasing an established link again.

**Architecture:** Replace the single-tier MBI dictionary at `ledger.py:1338` with a three-step resolution in a new `app/commission/backlink.py` module: (1) join `source_ref` → `PolicyPayment` → `Policy.customer_id` (the payment sibling already resolved at ingest with the full tier stack + crosswalk); (2) fall back to the shared `_match_policy` resolver for rows with no payment sibling (UHC's decomposed `::r`/`::o` refs); (3) on a miss, leave the existing `customer_id` untouched. A one-time idempotent backfill script repairs history using the same module.

**Tech Stack:** Python 3.10, Flask 3.0, Flask-SQLAlchemy, PostgreSQL 16 (prod) / SQLite in-memory (tests), pytest.

## Global Constraints

- **NO schema change, NO migration.** Migration head stays 042. — spec §"Migration: none".
- **The fix touches `customer_id` ONLY.** Never `raw_amount`, `split_rate`, `classification`, `agent_id`, `writing_agent_raw`, `member_name`, `mbi`, or `carrier_member_id`. Money must be provably unchanged. — spec §4 "Out".
- **NEVER overwrite a non-NULL `customer_id` with NULL.** A resolution miss leaves the existing link alone. This is the erasure bug being fixed. — spec §2 Decisions.
- **Multi-tenant:** every query filters `agency_id`. — CLAUDE.md.
- **`_match_policy` is NOT modified** — not its tiers, not its `status="active"` index. It is called as-is. — spec §4 "Out".
- **Devoted HRA in-string name parsing is OUT OF SCOPE.** — spec §4/§6.
- **The legacy `build_payments` path (`routes.py:1274`) is NOT touched.** — spec §4 "Out".
- Resolution order is fixed: payment-sibling → `_match_policy` fallback → leave alone. — spec §2.
- Backfill must be idempotent and offer `--dry-run` (default) / `--apply`. — spec §5b.
- Full suite green; baseline **776**. — spec §5.

**Verified facts the implementer can rely on (measured on live prod 2026-08-06):**
- `PolicyPayment.source_ref` is written at `app/commission/ingest.py:74`; `CommissionLineItem.source_ref` at `ledger.py`. They align **100% for Humana (676/676), BCBS (647/647), Aetna (138/138)**; UHC is 3,996/6,495 because UHC's extractor emits decomposed `::r`/`::o` sibling refs with no payment counterpart — this is exactly why step 2 exists.
- `ingest_statement` (creates/matches customers + payments) is called at `routes.py:1022-1023`, BEFORE `persist_line_items` at `routes.py:1030-1031`, inside the same `try`. Identity exists when the ledger writes.
- `_match_policy(item, carrier, agency_id, mbi_map, carrier_id_map, name_map)` at `payments.py:390` is a **pure function** — no DB writes, no session mutation. It returns `(policy_id, confidence_str)` or `(None, "unmatched")`.
- Its lookup maps are built at `payments.py:441-443` and `_build_name_index` at `payments.py:376`.

---

### Task 1: `resolve_line_item_customer` — the shared resolution helper

**Files:**
- Create: `app/commission/backlink.py`
- Test: `tests/test_ledger_backlink.py` (new)

**Interfaces:**
- Consumes: `PolicyPayment`, `Policy`, `CommissionLineItem` models; `_match_policy` + `_build_name_index` from `app/commission/payments.py`.
- Produces:
  - `build_backlink_context(agency_id)` → an opaque context object holding the three prebuilt lookup maps + a `source_ref → customer_id` map. Built ONCE per statement, not per row.
  - `resolve_customer_id(ctx, *, source_ref, carrier, mbi, carrier_member_id, member_name)` → `int | None`. Applies step 1 then step 2. Returns `None` when unresolved (the CALLER decides not to overwrite).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger_backlink.py`. Model the fixture on the existing `tests/test_commission_ledger.py` app/agency fixtures (read that file first for the established pattern).

```python
import pytest
from app.extensions import db
from app.models import (Agency, User, Customer, Policy, PolicyPayment,
                        CommissionStatement, CommissionLineItem)


@pytest.fixture
def ctx(app_fixture):           # reuse the project's existing app fixture pattern
    """Agency + a customer with one active policy + a paid statement."""
    app = app_fixture
    with app.app_context():
        ag = Agency(name="F"); db.session.add(ag); db.session.flush()
        cust = Customer(agency_id=ag.id, full_name="Mary Earnhardt")
        db.session.add(cust); db.session.flush()
        pol = Policy(agency_id=ag.id, customer_id=cust.id, carrier="BCBS",
                     member_id="106703512", full_name="Mary Earnhardt",
                     status="active")
        db.session.add(pol); db.session.flush()
        stmt = CommissionStatement(agency_id=ag.id, carrier="BCBS",
                                   period_label="July 2026")
        db.session.add(stmt); db.session.flush()
        yield app, ag.id, cust.id, pol.id, stmt.id


def test_resolves_via_payment_sibling(ctx):
    """Step 1: a payment row with the same source_ref carries the identity."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    with app.app_context():
        db.session.add(PolicyPayment(agency_id=aid, statement_id=sid, carrier="BCBS",
                                     policy_id=pid, source_ref="bcbs::T::Sheet1::7"))
        db.session.commit()
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, source_ref="bcbs::T::Sheet1::7", carrier="BCBS",
                                  mbi=None, carrier_member_id=None, member_name=None)
        assert got == cid


def test_resolves_via_carrier_member_id_fallback(ctx):
    """Step 2: no payment sibling, but carrier_member_id matches a policy.
    This is the BCBS case that fails today — BCBS rows carry NO mbi."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    with app.app_context():
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, source_ref="bcbs::T::Sheet1::99", carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name=None)
        assert got == cid


def test_returns_none_when_unresolvable(ctx):
    """No sibling, no id match, no name match -> None (caller must not overwrite)."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    with app.app_context():
        c = build_backlink_context(aid)
        got = resolve_customer_id(c, source_ref="bcbs::T::Sheet1::404", carrier="BCBS",
                                  mbi=None, carrier_member_id="NO_SUCH_ID",
                                  member_name="Nobody Here")
        assert got is None


def test_payment_sibling_wins_over_tiers(ctx):
    """Step 1 takes precedence over step 2 when both could resolve."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    with app.app_context():
        other = Customer(agency_id=aid, full_name="Other Person")
        db.session.add(other); db.session.flush()
        opol = Policy(agency_id=aid, customer_id=other.id, carrier="BCBS",
                      member_id="999", full_name="Other Person", status="active")
        db.session.add(opol); db.session.flush()
        db.session.add(PolicyPayment(agency_id=aid, statement_id=sid, carrier="BCBS",
                                     policy_id=opol.id, source_ref="bcbs::T::Sheet1::5"))
        db.session.commit()
        c = build_backlink_context(aid)
        # carrier_member_id points at cust, but the payment sibling points at other
        got = resolve_customer_id(c, source_ref="bcbs::T::Sheet1::5", carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name=None)
        assert got == other.id


def test_agency_scoped(ctx):
    """A payment/policy in another agency must never resolve."""
    app, aid, cid, pid, sid = ctx
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    with app.app_context():
        ag2 = Agency(name="Other"); db.session.add(ag2); db.session.flush()
        c = build_backlink_context(ag2.id)
        got = resolve_customer_id(c, source_ref="bcbs::T::Sheet1::7", carrier="BCBS",
                                  mbi=None, carrier_member_id="106703512",
                                  member_name="Mary Earnhardt")
        assert got is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ledger_backlink.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.commission.backlink'`.

- [ ] **Step 3: Write the implementation**

Create `app/commission/backlink.py`:

```python
"""
Shared customer back-link resolution for commission ledger rows.

WHY THIS EXISTS: `persist_line_items` used to resolve its customer link with a
single-tier MBI dictionary, which was strictly weaker than the resolver
`policy_payments` already uses at ingest — and it assigned unconditionally, so a
miss ERASED an existing link. BCBS went 213/213 (May) -> 199/216 (June) ->
0/218 (July) as re-uploads wiped prior links, because BCBS commission rows carry
NO MBI at all (only `carrier_member_id`).

RESOLUTION ORDER (see docs/superpowers/specs/2026-08-06-ledger-customer-backlink-repair-design.md):
  1. source_ref -> PolicyPayment -> Policy.customer_id. The payment sibling
     already resolved at ingest with the full tier stack + the carrier crosswalk,
     so the ledger INHERITS its answer and the two tables cannot diverge.
     Measured: recovers 537 of 641, a strict superset of re-resolving.
  2. Fall back to the shared `_match_policy` resolver (MBI -> carrier_member_id ->
     fuzzy name) for rows with no payment sibling — notably UHC's decomposed
     `::r`/`::o` refs, which have no payment counterpart by construction.
  3. Return None. The CALLER must leave any existing customer_id alone.
"""

from app.extensions import db
from app.models import Policy, PolicyPayment


class BacklinkContext:
    """Prebuilt lookup maps for one agency. Build ONCE per statement, not per row."""

    __slots__ = ("agency_id", "by_source_ref", "mbi_map", "carrier_id_map", "name_map")

    def __init__(self, agency_id, by_source_ref, mbi_map, carrier_id_map, name_map):
        self.agency_id = agency_id
        self.by_source_ref = by_source_ref
        self.mbi_map = mbi_map
        self.carrier_id_map = carrier_id_map
        self.name_map = name_map


def build_backlink_context(agency_id):
    """Build the agency-scoped lookup maps used by resolve_customer_id()."""
    from app.commission.payments import _build_name_index

    # Step-1 map: source_ref -> customer_id, via the already-resolved payment row.
    by_source_ref = {}
    rows = (db.session.query(PolicyPayment.source_ref, Policy.customer_id)
            .join(Policy, Policy.id == PolicyPayment.policy_id)
            .filter(PolicyPayment.agency_id == agency_id,
                    PolicyPayment.source_ref.isnot(None),
                    Policy.customer_id.isnot(None))
            .all())
    for sref, cust_id in rows:
        if sref:
            by_source_ref[sref] = cust_id

    # Step-2 maps: mirror what payments.build_payments() builds for _match_policy.
    all_policies = (Policy.query
                    .filter_by(agency_id=agency_id, status="active")
                    .with_entities(Policy.id, Policy.full_name, Policy.mbi,
                                   Policy.member_id, Policy.carrier)
                    .all())
    mbi_map = {p.mbi: p.id for p in all_policies if p.mbi}
    carrier_id_map = {(p.carrier, p.member_id): p.id
                      for p in all_policies if p.member_id}
    name_map = _build_name_index(agency_id)
    return BacklinkContext(agency_id, by_source_ref, mbi_map, carrier_id_map, name_map)


def resolve_customer_id(ctx, *, source_ref, carrier, mbi, carrier_member_id,
                        member_name):
    """Resolve one ledger row to a customer_id, or None.

    None means UNRESOLVED, not "clear the link" — the caller must leave any
    existing customer_id untouched (see the erasure bug in this module's docstring).
    """
    # 1. The payment sibling already did the work.
    sref = (source_ref or "").strip()
    if sref:
        hit = ctx.by_source_ref.get(sref)
        if hit is not None:
            return hit

    # 2. Fall back to the shared resolver, then policy -> customer.
    from app.commission.payments import _match_policy
    item = {"mbi": mbi or "", "carrier_member_id": carrier_member_id or "",
            "member_name": member_name or ""}
    policy_id, _confidence = _match_policy(item, carrier, ctx.agency_id,
                                           ctx.mbi_map, ctx.carrier_id_map,
                                           ctx.name_map)
    if policy_id is None:
        return None
    pol = (Policy.query
           .filter_by(id=policy_id, agency_id=ctx.agency_id)
           .with_entities(Policy.customer_id)
           .first())
    return pol.customer_id if pol else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ledger_backlink.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/commission/backlink.py tests/test_ledger_backlink.py
git commit -m "feat: shared customer back-link resolver (payment sibling, then _match_policy)"
```

---

### Task 2: Wire the resolver into `persist_line_items` + stop the erasure

**Files:**
- Modify: `app/commission/ledger.py` (`persist_line_items`, ~lines 1296-1347)
- Test: `tests/test_ledger_backlink.py` (extend)

**Interfaces:**
- Consumes: `build_backlink_context(agency_id)` + `resolve_customer_id(...)` from Task 1.
- Produces: `persist_line_items` keeps its existing signature `(carrier, drafts, statement, agency_id, agent_resolver=None) -> int`. No caller changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ledger_backlink.py`:

```python
def test_persist_never_erases_an_established_link(ctx):
    """THE REGRESSION TEST. A row that already has a customer_id must KEEP it
    when re-persisted with a draft that cannot be resolved. This is the BCBS
    199/216 -> 0/218 case."""
    app, aid, cid, pid, sid = ctx
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
```

✅ VERIFIED — `LineItemDraft` (dataclass, `ledger.py:35-49`) declares exactly:
`carrier, source_ref, raw_amount, classification, split_rate=None, payment_type=None,
member_name="", mbi=None, carrier_member_id=None, writing_agent_raw="", effective_date=None,
term_date=None`. Every field used in the tests above exists. No adjustment needed.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_ledger_backlink.py -q`
Expected: FAIL — `test_persist_never_erases_an_established_link` and
`test_persist_links_bcbs_row_with_no_mbi` both fail (customer_id is None).

- [ ] **Step 3: Replace the MBI dict in `persist_line_items`**

In `app/commission/ledger.py`, in `persist_line_items`:

**(a) DELETE** the `cust_by_mbi` block (the `from app.models import Customer` import, the `mbis`
set comprehension, and the `col = Customer.humana_id if ... else Customer.mbi` query loop).

**(b) ADD** after the docstring, before the `count = 0` line:

```python
    from app.commission.backlink import build_backlink_context, resolve_customer_id
    # Built ONCE per statement — resolve_customer_id() is a pure dict/query
    # lookup per row against these prebuilt maps.
    backlink_ctx = build_backlink_context(agency_id)
```

**(c) REPLACE** the unconditional assignment (was `existing.customer_id = cust_by_mbi.get(...)`) with:

```python
        # Resolve via the payment sibling, then the shared resolver. A miss must
        # NEVER clear an existing link — that erasure is the bug this fixes
        # (BCBS 199/216 -> 0/218 across a June->July re-upload).
        resolved_cid = resolve_customer_id(
            backlink_ctx, source_ref=d.source_ref, carrier=carrier,
            mbi=d.mbi, carrier_member_id=d.carrier_member_id,
            member_name=d.member_name)
        if resolved_cid is not None:
            existing.customer_id = resolved_cid
```

**(d) UPDATE** the docstring: replace the "back-linked to its Customer by MBI" sentence with a
description of the payment-sibling-then-resolver order and the never-clear rule.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_ledger_backlink.py tests/test_commission_ledger.py -q`
Expected: PASS. Then the full suite: `python3 -m pytest -q` — expected 776 + the new tests, 0 failures.
⚠ If an existing test asserted the old MBI-only behavior, UPDATE it to the new resolution order —
do NOT delete it.

- [ ] **Step 5: Commit**

```bash
git add app/commission/ledger.py tests/test_ledger_backlink.py
git commit -m "fix: ledger back-links customer via payment sibling + resolver, never erases a link"
```

---

### Task 3: One-time backfill script for the existing 641

**Files:**
- Create: `scripts/backfill_ledger_customer_links.py`
- Test: `tests/test_ledger_backlink.py` (extend)

**Interfaces:**
- Consumes: `build_backlink_context` / `resolve_customer_id` (Task 1).
- Produces: `backfill_ledger_links(agency_id, apply=False) -> dict` with keys
  `examined`, `resolved`, `unresolved`, `by_carrier` (dict carrier → resolved count).
  Importable so the test can drive it without a subprocess.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ledger_backlink.py`:

```python
def test_backfill_is_idempotent_and_dry_run_is_safe(ctx):
    app, aid, cid, pid, sid = ctx
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_ledger_backlink.py -k backfill -q`
Expected: FAIL — `ModuleNotFoundError: scripts.backfill_ledger_customer_links`.

- [ ] **Step 3: Write the script**

Create `scripts/backfill_ledger_customer_links.py`. Follow the established script pattern in
`scripts/` (read `scripts/backfill_override_sibling_customer.py` first — same dry-run/--apply shape).

```python
"""
One-time backfill: link existing CommissionLineItem rows to their Customer.

Repairs the 641 rows left unlinked by the pre-fix `persist_line_items` (single-tier
MBI lookup that also erased links on re-upload). Uses the SAME resolution order as
the live path, so the backfill and future uploads cannot disagree.

TOUCHES `customer_id` ONLY — never raw_amount, split_rate, classification, or
agent_id. Money is provably unchanged.

Usage (on the VPS):
    PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
        scripts/backfill_ledger_customer_links.py            # dry run (default)
    PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 \
        scripts/backfill_ledger_customer_links.py --apply
"""

import argparse
import sys

from app import create_app
from app.extensions import db
from app.models import CommissionLineItem
from app.commission.backlink import build_backlink_context, resolve_customer_id

# Only rows that represent real member money. Overrides/HRA are intentionally
# excluded — they mirror the same classification filter the /unassigned page uses.
_CLASSES = ["agent_commission", "chargeback"]


def backfill_ledger_links(agency_id, apply=False, sample=0):
    ctx = build_backlink_context(agency_id)
    rows = (CommissionLineItem.query
            .filter(CommissionLineItem.agency_id == agency_id,
                    CommissionLineItem.customer_id.is_(None),
                    CommissionLineItem.classification.in_(_CLASSES))
            .all())
    stats = {"examined": len(rows), "resolved": 0, "unresolved": 0, "by_carrier": {}}
    shown = 0
    for r in rows:
        cid = resolve_customer_id(
            ctx, source_ref=r.source_ref, carrier=r.carrier, mbi=r.mbi,
            carrier_member_id=r.carrier_member_id, member_name=r.member_name)
        if cid is None:
            stats["unresolved"] += 1
            continue
        stats["resolved"] += 1
        stats["by_carrier"][r.carrier] = stats["by_carrier"].get(r.carrier, 0) + 1
        if sample and shown < sample:
            print(f"  {r.carrier:12} {(r.member_name or '(none)')[:28]:28} "
                  f"${r.raw_amount:>10.2f}  -> customer {cid}")
            shown += 1
        if apply:
            r.customer_id = cid
    if apply:
        db.session.commit()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the links (default is a dry run)")
    ap.add_argument("--agency-id", type=int, default=1)
    ap.add_argument("--sample", type=int, default=15,
                    help="print this many proposed links for eyeballing")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        print(f"{'APPLYING' if args.apply else 'DRY RUN'} "
              f"(agency {args.agency_id})\n")
        s = backfill_ledger_links(args.agency_id, apply=args.apply,
                                  sample=args.sample)
        print(f"\nexamined   : {s['examined']}")
        print(f"resolved   : {s['resolved']}")
        print(f"unresolved : {s['unresolved']}")
        for carrier, n in sorted(s["by_carrier"].items(),
                                 key=lambda kv: -kv[1]):
            print(f"   {carrier:14} {n}")
        if not args.apply:
            print("\n(dry run — nothing written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

✅ VERIFIED — `from app import create_app` is the established pattern
(`scripts/backfill_override_sibling_customer.py:20`, the closest sibling script — same dry-run/--apply
shape, also a customer_id-only backfill). Import as written.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_ledger_backlink.py -q`
Expected: PASS (all tests incl. backfill).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: 776 baseline + new tests, **0 failures**. Record the count.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_ledger_customer_links.py tests/test_ledger_backlink.py
git commit -m "feat: idempotent backfill for existing unlinked ledger rows (dry-run default)"
```

---

## Deployment (human-gated — NOT part of the subagent build)

Per spec §5b, after the opus whole-branch review passes:

1. Merge to `main`, deploy: `git pull && ./venv/bin/pip install -r requirements.txt && systemctl restart founders-portal` (**no `flask db upgrade` — there is no migration**).
2. DB backup: `PGPASSWORD=<from .env> pg_dump -U founders_user -h localhost founders_portal > /root/founders_pre_backlink_$(date +%Y%m%d_%H%M%S).sql`
3. Dry run, and **Tim eyeballs the sample output**:
   `PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/backfill_ledger_customer_links.py`
   Expected: examined ≈ 641, resolved ≈ 537, unresolved ≈ 104.
4. `--apply`, then verify:
   - `/customers/unassigned?cat=match` drops 641 → ~104.
   - Money unchanged: `SELECT carrier, count(*), round(sum(raw_amount)::numeric,2) FROM commission_line_items GROUP BY carrier;` matches the pre-backfill values exactly.
   - Confirm the restart cycled (`ActiveEnterTimestamp` advanced).

---

## Self-Review

**1. Spec coverage:**
- §2 step 1 (payment sibling) → Task 1 `resolve_customer_id` step 1 + `by_source_ref` map. ✅
- §2 step 2 (`_match_policy` fallback) → Task 1 step 2. ✅
- §2 step 3 / Decisions (never overwrite with NULL) → Task 2 step (c) `if resolved_cid is not None` + `test_persist_never_erases_an_established_link`. ✅
- §4 "touches customer_id only" → `test_persist_does_not_touch_money_fields` + deploy money check. ✅
- §4 "`_match_policy` NOT modified" → called as-is; no task edits `payments.py`. ✅
- §4 Devoted HRA out of scope → no task touches the Devoted extractor. ✅
- §5 testing (per-step, regression, BCBS shape, idempotency, agency scoping) → Tasks 1-3. ✅
- §5b verification → Deployment section. ✅
- No migration → stated in Global Constraints and the deploy steps. ✅

**2. Placeholder scan:** No TBD/TODO. The two former ⚠ notes were resolved by the plan author against the real files and are now stated as ✅ VERIFIED facts (`LineItemDraft` field list at `ledger.py:35-49`; `from app import create_app` per `scripts/backfill_override_sibling_customer.py:20`), so no verification work is deferred to the implementer.

**3. Type consistency:** `build_backlink_context(agency_id) -> BacklinkContext` and
`resolve_customer_id(ctx, *, source_ref, carrier, mbi, carrier_member_id, member_name) -> int|None`
are used identically in Tasks 1, 2, and 3. `backfill_ledger_links(agency_id, apply=False, sample=0) -> dict`
matches its test (`dry["resolved"]`, `run2["resolved"]`). `persist_line_items` keeps its existing
signature, so no caller changes. `_match_policy`'s `(policy_id, confidence)` tuple return is unpacked
correctly. ✅
