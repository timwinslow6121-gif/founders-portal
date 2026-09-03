# Agent contract rates as a schedule — design

**Status:** approved, not yet built
**Date:** 2026-09-03
**Author:** Tim + Claude
**Deadline:** after AEP, before **February** — AJ computes the tiered portion when
AEP plan-swap initial commissions are paid.

## The problem

`AgentCarrierContract.split_rate` is **one undated number**. Tim's real contract
has three dimensions it cannot express:

1. **Annual step-up** — 50% in year 1, **+2.5% per year, capped at 70%**.
2. **A decaying 100% tier** — year 1, the first **$30,000** of commission pays at
   **100%** and the remainder at 50%. Year 2: first **$24,000** at 100%, remainder
   at 52.5%. The 100% portion shrinks each year until it reaches zero. This is not
   a rate — it is a piecewise function of **year-to-date commission**.
3. **Per-agent contract shapes, not variations** — Tim and (probably) Justin,
   Chris, Rebekah, maybe Mike on the above; **Brian** differs (agent *and* majority
   owner); **Betty** on a different contract entirely; **Anjana** retired, no longer
   soliciting but still paid a few hundred a month; **Alex Groves** flat 35%.

### What is NOT broken (correction, 2026-09-03)

An earlier reading of this said raising a rate would "silently rewrite every past
month." **That is wrong.** `split_rate` is **frozen onto each `CommissionLineItem`
at import time**, and `split_breakdown()` reads that stored value rather than
looking up the contract. Verified on production: no agent has more than one
distinct `split_rate` for a carrier, and Tim's 237 August UHC rows all carry 0.55.

So changing `AgentCarrierContract.split_rate` affects **future imports only**.
History is already immutable. This is a smaller build than first assumed.

The real gaps are narrower:

- The contract table knows only *now*. It cannot answer "what was Tim's rate in
  2025?", so a **re-import of an old statement re-stamps today's rate onto old
  rows** — and re-imports do happen (the June/July provenance backfill is still
  outstanding).
- Nothing records **why** a rate is what it is, or when it changed.
- **The tiered 100% portion has no home at all.** Not undated — absent.

## Decisions

### Record first, compute later (Tim, 2026-09-03)

Phase 1 **records** the schedule and shows AJ the year-to-date figure he needs.
He still applies the tier himself in February. Phase 2 computes it, only after the
portal's numbers have matched his hand math for a cycle or two.

Rationale: the portal is not yet trustworthy enough to be the system of record for
gross pay. Three parser bugs surfaced on 2026-09-02 alone, and in each case the
money was right only because AJ hand-checks. Earning that trust is a prerequisite,
not a formality.

### Rates become effective-dated; the stored line-item rate stays authoritative

A new `agent_contract_rate` table holds `(agent_id, carrier, effective_from, rate)`.
Import looks up the rate **as of the statement period**, not "now".

`CommissionLineItem.split_rate` remains the authoritative value for any row already
imported. The schedule decides what a *new* import stamps. This preserves the
existing immutability rather than replacing it, and fixes the re-import hazard.

### The schedule records what was ACTUALLY PAID, not what the contract says

Tim, 2026-09-03: in what the agents understood to be year 2, Brian **stepped the
tier down to $24,000 but left the rate at 50%** instead of raising it to 52.5% —
treating it as another year 1. He acknowledged it after the fact. Tim estimates it
cost him roughly **$8,000** in commission.

The mechanical lesson matters more than the money here: **the rate schedule and the
tier schedule moved independently.** A model that assumes "year N implies rate X
and tier Y" cannot represent what actually happened, and neither can a single
`split_rate`.

So `AgentContractRate` rows record **applied terms**, not contracted terms. Where
the two diverge, `note` carries why:

    effective_from 2025-01-01, rate 0.50, tier_amount 24000.00,
    note: "contract says 52.5% — 50% applied (Brian, acknowledged)"

If the table held contracted terms instead, the portal would show 52.5% for a year
paid at 50%, and every figure derived from it would be wrong — in the agent's
favour, which is its own kind of wrong. Recording what was paid makes a discrepancy
visible and durable instead of living in someone's memory.

⬜ **This also means the historical schedule must be reconstructed from what was
actually paid**, not assumed from the contract. `CommissionLineItem.split_rate` is
frozen per row and is therefore the evidence: the rate in force in any past period
can be read straight off the ledger.

### Do not infer who shares Tim's terms

Tim said "I think" and "not positive" about Justin, Chris, Rebekah and Mike.
**Every agent's schedule must come from AJ or the contract documents.** Getting one
wrong misstates that person's pay for a year. Seeding the table starts with Tim's
confirmed terms and Alex's flat 35%; everyone else is entered once confirmed.

## Design

### 1. Data model

```python
class AgentContractRate(db.Model):          # migration 043
    id             = Integer, pk
    agency_id      = FK agencies.id, indexed
    agent_id       = FK users.id, indexed, not null
    carrier        = String(64), nullable      # NULL = applies to all carriers
    effective_from = Date, not null            # inclusive
    rate           = Float, not null           # 0.525 = 52.5%
    tier_amount    = Numeric(10,2), nullable   # the 100% portion, e.g. 30000.00
    tier_rate      = Float, nullable, default 1.0
    note           = Text
    created_by_id  = FK users.id
    created_at     = DateTime
    __table_args__ = UniqueConstraint(agent_id, carrier, effective_from)
```

`carrier` nullable means one row can set an agent's rate across every carrier —
Tim's step-up is contract-wide, not per-carrier. A carrier-specific row overrides
the general one for that carrier.

`tier_amount` / `tier_rate` are **recorded in phase 1 and not applied**. They exist
so the schedule is complete and auditable before anything computes from it.

`AgentCarrierContract.split_rate` stays as-is — it remains what import stamps when
no schedule row covers the period, so nothing breaks on day one.

### 2. Rate resolution

One accessor, the single place a rate is decided:

```python
def rate_for(agent_id, carrier, as_of: date) -> float | None
```

Resolution order: the newest `AgentContractRate` for that agent whose
`effective_from <= as_of`, preferring a carrier-specific row over a
carrier-agnostic one; falling back to `AgentCarrierContract.split_rate`; returning
`None` if the agent has no contract at all.

`None` must mean **quarantine**, never a fabricated default — see the separate
unknown-agent quarantine item in BACKLOG.md. That work and this share this
accessor.

Import passes the **statement period**, not `date.today()`, so a re-import of a
May statement re-stamps May's rate.

### 3. Recording the schedule (phase 1)

An admin screen under Agent Settings showing each agent's rate timeline: effective
date, rate, optional tier, note. Adding a row is how a raise is applied — the
history stays visible rather than being overwritten.

The **YTD figure AJ needs already exists**: `_ledger_ytd_total(agent_id,
agency_id, year)` in `app/commission/recap.py`. Phase 1 surfaces it per agent
alongside their tier amount and the remaining headroom
(`tier_amount - ytd_gross`), so February's calculation is read off the screen
instead of assembled by hand.

Phase 1 changes **no money**. It records, resolves and displays.

### 4. Computing the tier (phase 2, later)

Deferred until phase 1's numbers have matched AJ's hand math for at least one
cycle. When built, the tier splits a row against year-to-date gross: the portion
below `tier_amount` pays at `tier_rate` (100%), the remainder at the schedule rate.
Rows must be applied in a deterministic order (statement date, then `source_ref`)
or the tier boundary lands on a different row each run.

**Open question that changes phase 2's scope, must be answered first: has the 100%
tier ever run through the portal, or has AJ always computed it by hand and entered
only the resulting split?** If the latter, every figure reconciled to date is the
**post-tier** number — correct, but not gross. Tim's description of the workflow
("compute an agent's gross pay, subtract the threshold amount, then apply the
contract rate at the beginning of next year") suggests hand-computed. Confirm
before building.

## Open questions for AJ

- **Which agents share Tim's terms?** Justin, Chris, Rebekah, Mike — unconfirmed.
- **Does the increase land on the contract anniversary or 1 January?** Decides
  per-agent-dated vs one portfolio-wide event.
- **Brian, Betty, Anjana, Alex** — each needs its own schedule. Anjana is retired
  (no new business, still paid); Alex's increase schedule and cap are unknown.
- **Has the tier ever been computed inside the portal?** (see §4)

## Testing

- `rate_for` returns the rate in force on a past date, not the current one
- A carrier-specific row overrides a carrier-agnostic one for that carrier
- No schedule row → falls back to `AgentCarrierContract.split_rate`
- No contract at all → returns `None` (quarantine, never a default)
- **Re-importing an old statement re-stamps the OLD rate** — the regression this
  prevents
- Existing line items are untouched by adding a schedule row (history immutable)
- Phase 1 changes no money: ledger and payment totals identical before and after
