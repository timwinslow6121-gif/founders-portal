# Commission → Customer Sync — Design Spec

**Date:** 2026-06-03
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Supersedes/resumes:** `docs/superpowers/Ideas/SESSION-NOTES-commission-customer-sync.md` (paused 2026-06-03 awaiting AJ's raw files; files arrived, brainstorm resumed)

## Problem

Uploading a commission file (Admin@, for Mike/Justin/Chris/Brian/Anjana) creates
`CommissionStatement` + `PolicyPayment` rows but **never creates `Customer` records**.
`commission/routes.py` and `payments.py` parse a customer-name column but never write
the `Customer` model. Those agents' books are therefore invisible in the customer
database. The fix: make commission upload a producer of customer + AOR facts, not just
payment facts — without ever double-paying a month or silently creating wrong money.

## Source data

AJ's **raw, unaltered** commission files (16 files) live in
`docs/Commission DL/Raw commissions docs from AJ/`. The earlier `Commission docs/`
files were agent-CLEANED and must NOT be used as the parser basis. Per-carrier raw
structure and row-type vocabulary verified against these files — see the
"Per-carrier reference" section below.

## Locked decisions (do not re-litigate)

From the paused session, confirmed/extended against raw data:

1. **Unified pipeline** — each row = a payment fact AND a customer/AOR fact, in one
   transaction. Guarantees "every payment has a customer." This sync is the *producer*
   of AOR-interval data the (paused) customer-access model and the retention-KPI layer
   will *consume* — so it is correctly sequenced first.
2. **Stub customers** — `Customer(stub=True, source='commission_import')` created only
   on a member's **first-ever** appearance when no MBI/DOB exists to match a human;
   auto-promote when BOB import or agent edit fills the gaps.
3. **Idempotent re-upload** — keyed on a stable identifier; no duplicate customers, no
   stacked AOR intervals on re-run.
4. **Dedup by stable ID, never by name** — proven by BCBS "Reynolds,Richard E 2"
   (same `Customer No 106818257`, mangled name).
5. **Generic carrier crosswalk** — match an existing `Policy` by
   `(carrier, member_id)` → reuse its `customer_id`. This is the deterministic monthly
   re-link that kills stub-proliferation. No BCBS-specific code.
6. **Carrier switch into a no-MBI carrier** = suggest-link / human-confirm (provenance
   pattern). Never silent merge, never silent duplicate.
7. **Carrier switch** = term the old policy (term_date + status='termed') + open a new
   Policy + new AOR interval. Preserve full history. Overlap month allowed.
8. **AOR intervals double as a KPI source** — capture a `rapid_disenroll` flag now
   (`term_date − effective_date < 90d`); the dashboard is a later phase.
9. **UHC LOA lumped split** = inferred value + confidence + AJ override (provenance
   pattern). Do not make the statement compute a split it structurally cannot.
10. **Agent split & contracting authorization = `AgentCarrierContract`** (source of
    truth). Two separate concerns: `is_active` (authorization) and `split_rate`
    (amount). No active contract → row held as error (e.g. Betty + BCBS). Anjana =
    provenance-conditional split, flagged for AJ to verify.

## Architecture — Approach A: shared resolution service

The two halves already exist but were never connected: commission upload builds
payments (`build_payments`), BOB upload builds customers
(`_upsert_customer_from_policy`). Extract the identity/AOR logic into ONE
carrier-agnostic `resolve_customer()` service that **both** importers call. One
identity codepath → the locked rules cannot drift between importers. Carrier
normalizers (most already in `payments.py`) feed it a normalized record.

De-risk the refactor of `_upsert_customer_from_policy` by pinning current BOB behavior
with tests *before* extracting.

### Section 1 — the `MemberFact` (the seam)

Every carrier file is reduced by a per-carrier **normalizer** to one common shape.
The resolver only ever sees `MemberFact`s; it never knows the carrier.

```
MemberFact:
  carrier
  mbi                str | None        # None for BCBS; blank-for-AARP on UHC
  carrier_member_id  str | None        # BCBS Customer No, Devoted Member ID, etc.
  first_name, last_name, full_name
  dob                date | None       # rarely present in commission files
  effective_date     date | None
  term_date          date | None       # from disenroll/chargeback rows
  plan_contract, plan_pbp              # → Plan.cms_plan_id link
  plan_type
  writing_agent_raw                    # resolved to user via existing nickname logic
  resolved_agent_id
  row_class          ENROLLMENT | RENEWAL | CHARGEBACK | NON_CUSTOMER
  amount             Decimal           # may be negative (chargeback)
  is_agency_share    bool              # Healthspring Service Fee, Devoted Override sheet
  contract_active    bool              # AgentCarrierContract.is_active (agent, carrier)
  split_rate         float             # from contract row — NOT hard-coded
  agent_share        Decimal           # gross × split_rate, only if contract_active
  split_flag         None | 'no_contract' | 'provenance_conditional'
  source_ref         file + sheet + row index  (audit + idempotency key)
```

- `row_class` computed by the normalizer from each carrier's native vocabulary.
- **Paired-row collapse** happens *inside* the normalizer: Healthspring Service Fee +
  Broker Level, and Devoted Override + Agent Portion, emit ONE `MemberFact` per member
  (amount = agent share; agency share carried alongside) — the resolver sees one
  customer fact, not two.

### Section 2 — the resolver (identity & crosswalk)

`resolve_customer(fact) -> (customer, policy, actions[])`. Resolution order:

1. **Crosswalk** — match existing `Policy` by `(carrier, carrier_member_id)` → reuse
   `Policy.customer_id`. Deterministic monthly re-link; renewals/repeats land here and
   never re-stub.
2. **MBI** — if `fact.mbi`, match `Customer` by MBI (or `humana_id` for Humana) →
   reuse; create/attach Policy.
3. **Suggest-link** — no crosswalk, no MBI, but a normalized name+DOB near-match to an
   existing customer → create the stub/policy AND enqueue a `MatchSuggestion` for human
   confirm in the existing merge UI. Never auto-merges. (BCBS rows have no DOB, so this
   only fires once DOB exists from a prior BOB record/edit — until then a new BCBS-only
   person legitimately becomes a stub.)
4. **Stub** — nothing matches → `Customer(stub=True, source='commission_import')` +
   Policy. At most once per member, on first sighting.

Then, regardless of which path matched:
- **Carrier-switch detection** — customer has an *active* policy on a *different*
  carrier and this fact is ENROLLMENT → term old policy, open new Policy + new AOR
  interval (overlap month allowed).
- **rapid_disenroll** — `term_date − effective_date < 90d` → set flag on the policy.
- **manually_edited guard** — never overwrite PII on an edited customer (existing rule).

### Section 3 — data model changes

**Migration 020 — sync support:**
- `customers.stub` (Boolean, default False)
- `customers.source` (String) — `'commission_import' | 'bob' | 'healthsherpa' | 'manual'`
- `policies.rapid_disenroll` (Boolean, default False)
- `policies.commission_split_flag` (String, nullable) —
  `None | 'no_contract' | 'provenance_conditional'`

*(CLAUDE.md's planned "migration 018" column list named Customer.stub/source +
CommissionStatement.aor_flags_json, but 018 was consumed by SOB work. These columns
become migration 020; same intent, corrected number. `aor_flags_json` added here too if
not already present.)*

**New table — `match_suggestions`** (suggest-link queue, path 3):
```
id, agency_id, source_member_fact_json, suggested_customer_id,
confidence ('name_dob' | 'name_only'), status ('pending'|'confirmed'|'rejected'),
created_at, resolved_by, resolved_at
```

**Reuse, no new structure:** the crosswalk IS a `Policy` lookup on
`(carrier, member_id)` (already indexed). AOR intervals reuse `CustomerAorHistory`.
AOR discrepancy flags reuse `CommissionStatement.aor_flags_json`.

### Section 4 — unified upload pipeline (control flow)

```
1. Detect carrier (existing _detect_carrier)
2. Normalizer[carrier](sheets) → [MemberFact, ...]
3. Statement duplicate guard (see below) — BEFORE any write
4. FOR EACH MemberFact, in ONE transaction per statement:
     a. resolve_customer(fact) → (customer, policy, actions)
     b. lifecycle: carrier-switch term + new AOR interval; rapid_disenroll flag
     c. AgentCarrierContract:
          no active contract → split_flag='no_contract', HOLD (error tab), no share
          Anjana            → split_flag='provenance_conditional', default split, FLAG
          else              → agent_share = gross × split_rate
     d. write PolicyPayment (existing), link to resolved policy
     e. CHARGEBACK / NON_CUSTOMER → payment/lifecycle only, NO customer create
     f. AOR discrepancy (writing agent ≠ stored primary_agent) → aor_flags_json, no auto-change
5. Commit (atomic per statement — one bad row rolls back that whole file).
```

**Duplicate-statement guard (the double-pay preventer).** Two independent safeguards:

- **Row-level idempotency (makes double-pay impossible):** every `PolicyPayment` keys
  on `source_ref` (file+sheet+row) + crosswalk. Re-running the same file updates rows
  in place; never inserts duplicates.
- **Statement-level detector (makes the mistake visible):** fingerprint =
  `(carrier, agency, statement_date, member_row_count, sum_of_amounts)` — NOT the
  filename. On upload, before writing:
  - **Exact match** to a committed statement → **BLOCK by default + explain** what it
    matched (carrier, date, import date, row count, total) + offer a clearly-labeled
    **"Replace existing statement"** button.
  - **Same statement_date, overlapping members, different totals** → **WARN + preview
    overlap**, require explicit confirm.
  - **New period** → proceeds.

**Replace mode = update-in-place by row:** match incoming rows to existing via
source_ref/crosswalk, update amounts/dates in place; rows absent from the new file
marked superseded. No delete; history and manual edits preserved; no double-pay.

**Error-reporting standard:** every held/error/skipped row reports **expected vs got vs
fix** (e.g. "Row 47 (Healthspring): expected a Broker Level row to pair with Service Fee
for member 71A2L3L49; got an unpaired Service Fee ($80); fix: agent share may be on a
separate statement — verify or assign manually."). Raw tracebacks → log only; the
actionable message → screen.

**Import result modal** extends the Phase-4 tabs, fed by `actions[]`:
New customers / Updated / Stubs created / Chargebacks / Held-no-contract / AOR flags /
Match suggestions.

### Section 5 — testing & build sequencing

**Testing** (local SQLite, no VPS/venv — mirrors `tests/test_plan_provenance.py`):
- Per-carrier normalizer unit tests, fixtured from the real raw files: correct
  `MemberFact`s, paired-row collapse, `row_class` mapping, chargebacks negative.
- Resolver tests: crosswalk re-link (no re-stub month 2), MBI reuse, carrier-switch
  term+new-interval, rapid_disenroll, stub-once, suggest-link enqueue (no auto-merge),
  manually_edited PII guard.
- Idempotency: upload twice → identical DB state, zero duplicate payments; replace-mode
  update-in-place.
- Money: `agent_share = gross × split_rate`; no-contract holds; Anjana flagged.

**Build sequencing** (small, independently shippable plans):
1. `MemberFact` + normalizers for clean-split carriers first
   (Healthspring, Devoted, BCBS, Aetna, Humana) — no inference needed.
2. `resolve_customer()` + crosswalk + stub + migration 020 + `match_suggestions`.
3. Carrier-switch lifecycle + rapid_disenroll + AOR intervals.
4. Duplicate-guard + replace-mode + expected/got/fix error reporting + modal tabs.
5. Split/authorization (contract gate, Anjana flag).
6. **UHC normalizer last** — lumped LOA split stays inferred + confidence + AJ override.

**Explicit non-goals (deferred, each a downstream consumer of data this build
produces):**
- Retention / rapid-disenroll KPI dashboard.
- Interval-aware customer-access model.
- HealthSherpa live wiring — the `resolve_customer()` service IS the integration point;
  when the agency account is provisioned and a live payload is captured (the handler
  already logs raw payloads at INFO), wiring it is a new normalizer + a resolver call,
  not a redesign. HealthSherpa, once live, closes the no-MBI gap by resolving identity
  at point-of-sale before the commission statement arrives.
- Anjana's exact zip/county/lead-source split rule (AJ has it; encode later).

## Per-carrier reference (verified against raw files 2026-06-03)

**File formats / detection traps:**
- BCBS: per-agent XLSX, sheet `Sheet1`, header row 0.
- Healthspring (`66_`,`67_`,`68_`,`71_`): XLSX, sheets Summary/Detail/Legacy; Detail header row 0.
- Devoted (`Founders Devoted…`): XLSX, sheets Total/Override/Agent Portion/HRA; member appears in BOTH Override and Agent Portion.
- Devoted per-agent (`20182775_Rebekah…xls`): extension `.xls` but bytes are `PK` = real XLSX. Sheets Summary/Detail/Misc.
- Aetna: XLSX, one sheet named for the agency, header row 0, agency-level multi-agent.
- UHC (`statement-2813549…xlsx`): XLSX, sheets Commission Transactions / Commission Summary / Held Transactions.
- Humana (`CommissionData (5).xls`): SpreadsheetML 2003 XML (broken first line `<xml version>`); pandas read_html→0 tables. Parse `<Worksheet>/<Row>/<Data>` via regex/ElementTree.

**Stable member identifier (for the 3-tier dedup MBI→carrier-id→name):**
- BCBS: NO MBI — only `Customer No` (policy-scoped: a plan switch yields a NEW Customer No for the same human). Name unreliable.
- Healthspring: `Medicare Beneficiary Identifier` (MBI) + `Member ID`.
- Devoted: 6-char `Member ID` (e.g. DS97W3) + `Member HICN`.
- Aetna: `Medicare Number` (MBI) + `Member ID` (NG…).
- UHC: `MedicareID` (MBI) — blank for AARP Medigap rows (only `AARP Member ID`).
- Humana: `UMID` (MBI-shaped) + `PID`.

**Row-type vocabulary → common taxonomy:**
- BCBS `Group Type`: FY (enroll), RENEW, ADJUSTMENT (chargeback), NEW. Agent in `Agent Name`.
- Healthspring `Payment Type`: "Initial - New to CMS" / "Initial - NOT New to CMS" / "Renewal" / "Disenrollment Initial" (chargeback, negative). Each member = TWO rows (`Payment Description` Service Fee → FOUNDERS agency share + Broker Level → agent). Collapse to one.
- Devoted `Commission Type`: "Initial - New" / "Initial - Not New". Negative Base/Admin Amount + a Disenroll Date = chargeback. Override sheet = agency share; Agent Portion = agent share; HRA sheet = $50 bonuses (NON_CUSTOMER).
- Aetna `Sales Event`: Renewal / "Pro-Rata Payment" / "Pro-Rata Disenroll" (negative chargeback). `CMS New` Y/N.
- UHC `Commission Action`: New / "New Chargeback" (negative) / Renewal. `Comp Type` I/R. `Held Transactions` sheet = unpaid ("Agent not licensed as…") — record, not paid.
- Humana `TxnTypeCd`: ARCM (renewal) / ARCF (first-yr) / MED2 (2nd-half first-yr) + rare ISPR/ISPZ/ISPO/MSRA/CRCF/HRAP/ICCF/ICFA. `Comment` mirrors it. Negative `PaidAmount` = chargeback. SplitPct=100 (pays Tim direct).

## Open items for AJ (non-blocking)
- Confirm exact split rates per agent (CLAUDE.md says Betty 0.525; Tim recalls 0.50 — reconcile).
- Anjana's exact provenance-conditional split rule (zip/county/lead-source thresholds).
- UHC LOA split ground truth (call UHC commissions) for seeding the inferred-split confidence.
