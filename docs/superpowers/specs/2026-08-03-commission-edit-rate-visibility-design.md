# Commission Edit — Contract-Rate Visibility & Mismatch Guard

**Status:** spec, awaiting review
**Date:** 2026-08-03
**Author:** Tim + Claude
**Migration:** none (UI + one serializer field)

---

## 1. The problem

AJ has repeatedly saved commission edits that pay an agent **100% of a line**
when their contract says otherwise. Confirmed instances: Mike Lauzurique's 38
PARTD rows (2026-08-01), Rebekah Long's 15 SEID rows and her BENSON renewal
(2026-08-03). Each time the money was wrong and nothing warned him.

He is not misusing the tool. **The UI does not tell him which of two
conventions he is in, and never shows the agent's rate.**

### 1.1 Two forms, two conventions, no visible difference

Both appear as inline rows in the same tables (quarantine, workbench, review,
Fidelity):

| | Resolve form | Edit form |
|---|---|---|
| Fields | `[agent ▾] [Override $]` | `[agent ▾] [Agent $] [Override $]` |
| Meaning | "Founders' share; compute the agent's" | "both final dollars; compute nothing" |
| Stored rate | agent's **contract rate** | **`1.0`**, hardcoded |
| Live preview | **yes** | **no** |

The only cue is that one form has one amount box and the other has two. Both
use bare placeholders (`"Agent $"`, `"Override $"`) in visually identical rows.

`edit_line_split()` (ledger.py:1214-1255) sets `line.split_rate = 1.0` at line
1254 unconditionally, and its docstring says why:

> The agent's entered dollars are stored as the FINAL payout… `split_rate` param
> is ignored (kept for back-compat)… This is what lets a special case like
> Anjana's 'keeps 100% of the post-override amount' stick through to her recap.

That is **correct for its purpose** — Anjana Patel keeps 100% on
non-Cannon-Pharmacy customers, which cannot be derived from a contract rate.
It is wrong whenever AJ uses the same form on an ordinary row.

### 1.2 The observed failure

```
#94   resolve  08-01 17:49   28.56@None  -> 28.56@0.55   (correct)
#260  edit     08-03 00:45   28.56@0.55  -> 25.21@1.0    (rate clobbered)
```

A resolve sets the rate correctly; a later edit silently overwrites it. AJ typed
`4.59` meaning *"the commission base"*; the form stored it meaning *"the agent's
final payout"*.

### 1.3 Why it stays invisible

`split_rate = 1.0` still satisfies the ledger invariant
(`Σ raw = Σ payout + keep`), so the statement balances to the penny. Only the
*allocation* is wrong. Same class as the PARTD lump: plausible, balanced, silent.

---

## 2. Goals / non-goals

**Goals**

1. Show the selected agent's contract rate for that carrier, **everywhere AJ
   enters or edits a split** (Tim's call: "everywhere AJ touches money").
2. Live-preview what the agent actually receives as he types — the resolve form
   already does this; the edit form must too.
3. **Warn before saving** an amount that implies 100% for an agent whose
   contract is not 100%.
4. Keep Anjana's 100% case reachable without extra friction.

**Non-goals**

- No change to `split_breakdown()`, `resolve_quarantine_line()` or the ledger
  invariant.
- Not removing the `split_rate = 1.0` convention (Anjana depends on it).
- Not adding a mode toggle or an extra required choice per edit — Tim's
  standing constraint is that every added selection is another thing to get
  wrong at 2am.
- No migration.

---

## 3. Design

### 3.1 Surface the rate (the core fix)

`fidelity_row()` (recap.py:474) is the single serializer feeding the Fidelity
table and the AJAX repaint, so the rate is added there once:

```python
"contract_rate": _contract_rate(li.agent_id, li.carrier, li.agency_id),
```

A small cached lookup (`(agent_id, carrier) -> split_rate`) keyed the same way
as `commission_line_resolve` (routes.py:1538-1542), falling back to `None` —
never a fabricated default. Rendered next to the agent picker on **every**
split-entry surface:

```
Mike Lauzurique — UHC contract 52.5%
```

Where a row's stored `split_rate` differs from the contract, show it plainly
(`stored 100% · contract 52.5%`) so a wrong row is legible at a glance without
opening the form.

### 3.2 Live preview on the edit form

Reuse the existing resolve-form preview (workbench template, `input.qr-money
[data-preview]`) rather than writing a second mechanism. As AJ types:

```
Agent $ [4.59]  Override $ [0.26]
    → Mike receives $4.59 of $4.85   ⚠ that is 100%; his UHC contract is 52.5%
```

The preview states the **outcome in dollars**, not the convention — that is what
makes the two forms self-describing without a label AJ has to interpret.

### 3.3 Mismatch warning (the guard)

On save, if `agent_amount` implies a rate that differs materially from the
agent's contract (tolerance ±0.5 cents on the derived payout), the form
**requires one confirmation click**:

> Mike Lauzurique's UHC contract is 52.5%, but this saves $4.59 of $4.85 —
> 100% to the agent, $0.00 to Founders. Save anyway?

Confirm-and-proceed, not a block: Anjana's rows are exactly this shape and must
remain one extra click, not a refusal. The confirmation is the seam that turns a
silent mistake into a deliberate decision.

Server-side, `commission_line_edit` accepts an explicit `confirm_off_contract=1`
and rejects an off-contract save without it, so the guard cannot be bypassed by
a stale form or a no-JS fallback.

### 3.4 What is NOT changed

`edit_line_split()` keeps storing `split_rate = 1.0`. The convention is sound;
the gap was that AJ could not see which convention he was in. Changing the
storage semantics would silently re-interpret every existing `manually_adjusted`
row, including Anjana's legitimate ones.

---

## 4. Affected surfaces

| Template | Form | Change |
|---|---|---|
| `commission_quarantine.html` | resolve + edit | rate shown; preview on edit |
| `commission_quarantine_workbench.html` | resolve + edit | same |
| `commission_review.html` | edit | same |
| `commission_fidelity.html` | edit (JS-built) | rate from `fidelity_row`; preview + guard |

The Fidelity view builds its edit form in JS on Edit-click (the ~4k-row perf
fix, merge 50a7f4a), so the rate must travel in the row JSON rather than be
rendered per row — otherwise the 2026-06-29 DOM-size regression returns.

---

## 5. Testing

1. `fidelity_row()` includes `contract_rate` for an agent with a contract, and
   `None` for one without — never a fabricated 0.55.
2. An off-contract save without `confirm_off_contract` is rejected (400/JSON
   error); with it, it succeeds and stores `1.0` as today.
3. An on-contract save needs no confirmation.
4. Anjana's 100% case still saves in one confirmation, and her stored rows are
   untouched by this change.
5. Regression: `split_breakdown()`, `resolve_quarantine_line()` and the
   per-carrier balance suite unchanged.
6. Fidelity DOM size does not regress (rate travels in JSON, not per-row markup).

---

## 6. Rollout

1. Merge → deploy (no migration).
2. Live-verify on the Fidelity view: rate renders, preview updates, an
   off-contract save prompts and then persists.
3. Watch the next UHC upload: with the PARTD parser fix (commit 17e3efc) AJ
   should have **no** PARTD rows to hand-edit at all — this guard is the net for
   whatever else he does touch.

---

## 7. Follow-ups (not in scope)

- **`split_rate = 1.0` is overloaded** — it means Anjana's by-design 100%, AJ's
  exact-dollars convention, and genuine errors, indistinguishable in the data.
  It has now produced two false-positive audits (26 rows / $257 on 2026-08-01;
  17 rows / $194 on 2026-08-03, of which only 1 was real). A `rate_reason` or a
  real contract type would make an off-contract report usable.
- **Anjana's arrangement is not modelled** — "100% when the customer is not a
  Cannon Pharmacy customer" is a contract rule AJ applies by hand every month.
  Modelling it (even as a per-agent flag) would remove the manual step and the
  ambiguity together.
- **DVH member names are formatted differently** (`"JANA BENSON"` vs
  `"BENSON, JANA"`) and carry no MBI, so one person shows twice in a recap.
  Cosmetic, but it prompted this investigation.
