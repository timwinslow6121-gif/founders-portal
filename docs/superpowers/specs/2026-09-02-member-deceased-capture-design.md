# Member deceased & termination-reason capture — design

**Status:** approved, not yet built
**Date:** 2026-09-02
**Author:** Tim + Claude

## The problem

**20 members that carriers have told us are deceased are marked `active` in the
portal right now.** They would receive an AEP mailing today.

The data is not missing. It is arriving in files we already ingest, in columns
the parsers discard:

| Carrier | Source | Column | Signal |
|---|---|---|---|
| UHC | commission statement | `Term Reason` | literal `"Death"` |
| Humana | BOB | `Deceased Date` | a date |

Neither is imported. Nothing in the schema records death at all — `Customer`
has no such field, and `Policy.term_reason` is free text populated on 17 of
5,540 rows.

Verified exposure as of 2026-09-02:

- **15 UHC members** with `Term Reason = "Death"` across the May and July
  statements (18 distinct MBIs found across every UHC file including the
  per-agent April/May books and the archive; 3 resolve to no customer record).
  Every one is `active` with **no term date at all**. Some died in April.
- **5 Humana members** with a `Deceased Date` in the August BOB — Jeanette
  Evans (8/11), Richard Golden (8/8), Kay Nesbitt (8/9), Casey Patterson
  (8/12), Barbara Walker (8/7).

### What this design does NOT solve

BCBS, HealthSpring and Devoted provide no death signal in any file we receive,
so deaths on those books stay invisible. Aetna has a `Term Reason Code` column
(134 populated: `92`×79, `13`×41, `T014`×8, `8`×5, `T090`×1) but the codes are
unlabeled and no description column exists — decoding it needs AJ or Aetna.

After this ships the portal knows about deaths for **UHC and Humana only**,
roughly 85% of the book by member count. That is an improvement, not a
guarantee, and should be described that way.

## Decisions

### Suppress, never delete or hide

A deceased customer stays fully visible: policies, payments, notes, history all
intact, with a badge naming the source (`Deceased — per UHC, 2026-04-30`).
Suppression is narrow and specific: excluded from mailing lists, campaigns and
outreach selection; flagged in exports.

The alternative — hiding or deleting — fails silently. A living customer wrongly
marked would vanish from their agent's book with nobody noticing, because they
would stop appearing anywhere. A visible badge is correctable; an absence is not.

Retention reinforces this. CMS requires 10-year retention on marketing and
enrollment records (SOAs, applications, call recordings), an obligation that does
not end at death, and HIPAA protects PHI for 50 years post-mortem. Nothing about
a death argues for deleting data. (Retention specifics should be confirmed with
AJ/Brian before being stated as compliance fact; the design is safe under any
reading because it never deletes.)

### Mark the person, term only what the carrier confirmed

`deceased_date` is a fact about the **person** and suppresses outreach
everywhere immediately. Policy **termination** stays per-carrier: UHC reporting
a death terms the UHC policy only. A BCBS Medigap held by the same person stays
active until BCBS says otherwise.

Rationale (Tim, 2026-09-02): death propagates SSA → CMS → carriers, so the other
carriers will report it themselves within a month or two. Auto-terming their
policies front-runs data already coming, while taking on false-positive risk.
Ancillary products are the clearest case for caution — how hospital indemnity and
DVH plans handle a death (benefit payout? conversion?) is not yet known from real
cases, so encoding a guess would be wrong.

Consequence, accepted deliberately: a deceased person may briefly show one termed
and one active policy, and remains counted in book totals until the second carrier
terms them. Overcounting is visible and self-correcting; undercounting hides
revenue.

### Exact unique-ID matching only — no fallback

Match on **MBI** (UHC) or **Humana ID** (Humana). If an ID does not resolve to
exactly one customer, **nothing is marked** and the row goes to review.

No name matching, no name+DOB, no fuzzy fallback. Three separate mismatch bugs
on 2026-09-02 came from exactly those techniques (name-prefix matching stitching
different people together; a one-to-one dict over a one-to-many relationship;
MBI-vs-member_id keying).

Tim's framing: *"it's worse to mark a person wrongly as deceased than to
accidentally send out a letter — people expect letters to trickle in for
deceased loved ones for a while after death, which is better than forgetting
someone by accident."* A missed death is a letter that should not have gone out:
visible and recoverable. A wrong match erases a living customer from their
agent's book: silent and not.

### Manual marking, by agents

Agents learn about deaths weeks before carriers do — a family member calls, or an
obituary appears. Capture-only would leave the portal permanently behind on the
one fact that most needs to be current before AEP.

Manual marking also gives the false-positive escape hatch a home: the same
control both sets and clears.

**Manual marking sets `deceased_date` but never terms a policy.** An agent
knowing someone died does not mean the carrier has processed it, and a
manually-termed policy would diverge from the carrier's book — the reconciliation
problem this codebase has spent considerable effort fixing. Suppression is
immediate; termination follows the carrier.

## Design

### 1. Data model

One migration, two columns:

```python
Customer.deceased_date    = db.Column(db.Date, index=True)          # nullable
Policy.term_reason_raw    = db.Column(db.String(64))                # nullable
```

`deceased_date` drives all suppression. `term_reason_raw` holds the carrier's own
words verbatim (`"Death"`, `"Member Termination"`, `"Enrollment in Another
Plan"`) so nothing is lost to interpretation — the existing free-text
`Policy.term_reason` stays as-is for human notes.

`deceased_date` is added to `PROVENANCE_FIELDS` in `app/customer_provenance.py`,
inheriting the existing trust ladder (`carrier_import` < `agent_entered` <
`human_verified`). This gives three properties:

- who/what/when set it is recorded
- an agent's mark outranks a carrier import
- **a later import can never silently clear an existing `deceased_date`** — the
  same never-erase rule used by the ledger back-link

⚠ **The carrier-import writer does not exist yet.** `app/customer_provenance.py`
currently exposes only `set_human_value()`, and the module is not wired into
`app/upload.py` or `app/commission/resolver.py` at all — those paths write
customer fields directly via `_fill_if_blank`. This work must therefore add a
`set_carrier_value(customer, field, value, source)` writer implementing the same
precedence check, and use it for `deceased_date`. Retrofitting the other
provenance fields onto it is explicitly **not** in scope — one new field, one new
writer.

No new table. Nothing is ever deleted.

### 2. Capture

**UHC** (`app/commission/normalizers.py`, `normalize_uhc`): read `Term Reason`
into `MemberFact.term_reason_raw`. Where the value is `"Death"`
(case-insensitive), set `deceased_date` from the row's term date.

**Humana** (`app/parsers/humana.py`): read `Deceased Date` into the record dict;
`_upsert_customer_from_policy` writes it to the customer.

Both write via the new `set_carrier_value(...)` writer (see §1) so the trust
ladder and never-erase rule apply.

Resolution is exact-ID only, as decided above. A row whose ID resolves to 0 or
more than 1 customer marks nobody and is recorded for review.

`"Enrollment in Another Plan"` (22 rows in the July UHC file) is **captured but
not acted upon**. It is a switcher signal, and acting on it belongs to the
carrier-switch redesign — a separate piece of work. Storing it now means the data
exists when that is built.

### 3. Suppression

A single accessor is the only place the rule lives:

```python
def is_contactable(customer) -> bool:
    return customer.deceased_date is None
```

Consumers:

- **Customer list** — deceased badge; excluded from mailing/campaign selection
- **CSV export** — a `Deceased` column, and the filter-provenance line states how
  many rows were excluded or flagged
- **Any future AEP mailing list** — must call this accessor

The customer profile shows a badge naming the source and date, with an inline
control to set or clear.

### 4. Manual marking UI

Inline on the customer profile, beside Medicaid and Language (the pattern agents
already use).

- **Set** — prompts for date of death (may be left unknown) and an optional note
  (`"son called 8/14"`). Writes at `agent_entered` trust.
- **Clear** — requires a reason. Clearing is the riskier direction and is
  recorded as such.

Date matters, not a checkbox: date of death determines whether a policy should
have termed and roughly when.

### 5. Backfill and review

`scripts/backfill_deceased.py`, dry-run by default:

- Sources: every UHC commission statement and per-agent BOB carrying `Term
  Reason` (May, July, plus the April/May per-agent books and archive), and the
  August Humana BOB
- Expected: **20 customers** (15 UHC + 5 Humana). 3 UHC MBIs resolve to no
  customer record and are reported, not forced.
- Gates: refuses any ID resolving to 0 or >1 customer; never overwrites an
  existing `deceased_date`; verifies payment and ledger totals unchanged before
  and after
- DB backup before apply, as with every money-adjacent change

A review list surfaces two categories:

1. death rows whose ID matched no customer
2. deceased customers still holding an active policy on **another** carrier —
   self-resolving when that carrier's next file lands, and the place where real
   HI/DVH death behaviour will first become observable

## Out of scope

- **Aetna `Term Reason Code`** — blocked on decoding the codes with AJ/Aetna
- **BCBS / HealthSpring / Devoted** — no death signal exists in their files
- **Acting on `Enrollment in Another Plan`** — belongs to the carrier-switch
  redesign, which must also fix `member_fact_from_bob_rec` hardcoding
  `RowClass.RENEWAL` (the reason a BOB upload can never trigger a carrier switch,
  leaving Kathy Rhodes, Deborah Cunningham and Sandra Elledge on two active MA
  plans each)
- **The 18 active-with-past-term-date policies** — mostly Humana `Future Active
  Policy` mid-year plan changes plus two paid-after-term cases; different root
  cause, separate fix

## Testing

- Parser tests against the **real** UHC and Humana files, asserting the exact
  counts above — the completeness invariant this codebase relies on
- Exact-ID matching: a name+DOB near-match must mark **nobody**
- Never-erase: re-importing a file that no longer mentions a death leaves
  `deceased_date` intact
- Trust ladder: an agent's mark survives a subsequent carrier import; an agent
  clearing a carrier mark sticks
- Carrier-scoped termination: a UHC death does not term a BCBS policy
- Manual marking sets `deceased_date` and terms nothing
- `is_contactable` excludes from export and list selection
- Backfill: dry-run reports 20, money identical before and after, idempotent on
  re-run
