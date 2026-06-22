# Policy / Payment Identity Recovery & AOR Traceability — Design

_Date: 2026-06-22 · Status: approved, ready for implementation plan_

## 0. Why this exists

Tim's principle, stated as the acceptance test: **every payment, policy, and customer
must trace back to the AOR.** Nothing blank, nothing of unknown origin — every record
has a known identity (who) and origin (where it came from), OR sits in a review queue
explicitly marked "needs a human." This is what makes the commissions trustworthy
end-to-end (Brian's trust + Tim's pay depend on it).

Discovered while fine-tuning the 2026-06-20 attribution round: a UHC agent-portal count
of 262 showed as 305 in the portal, which unravelled into a set of records that can't be
traced to an owner. This spec fixes the **data integrity**; the Carriers & Plans module
**UI** rebuild is a separate, smaller follow-up spec (it becomes mostly display work once
the data is clean).

## 1. The guarantee — four unbroken links (hard acceptance criteria)

Every record satisfies its link, OR appears in the Needs Identity hub. Live magnitudes
audited 2026-06-22:

| Link | Guarantee | Gap today |
| --- | --- | --- |
| **1. Payment → customer** | every `CommissionLineItem` resolves to a real customer, OR is explicitly a non-customer payment (override/hra/adjustment) | **428** NULL-customer line items that are agent_commission/chargeback (469 NULL total − 41 legit override/hra). Only ~5 have an MBI; rest need name/member-id match |
| **2. Policy → identity** | every active `Policy` has a name + member_id (no "- " rows) | **103** no-name active policies (94 UHC, 9 Aetna) |
| **3. Customer → agent** | every `Customer` has a `primary_agent_id`, or sits in "needs agent" | **38** unassigned customers |
| **4. Owned record → dated AOR interval** | every agent'd customer has a `CustomerAorHistory` interval (agent + carrier + effective + end) — ownership traceable through TIME | **2,353** customers have an agent but NO interval |

Plus the **51 `uhc::0::N` stub policies** (commission payments wearing a Policy costume;
15 wrongly inflated Tim's UHC) — these are a *Link-1* symptom (an unmatched payment that
also spawned a fake policy), fixed by re-pointing the payment + deleting the stub.

**In scope:** cleanup of all four gaps + **prevention** (stop new gaps accumulating).
**Out of scope:** the Carriers & Plans visual rebuild (next spec); the Round 2
reconciliation engine.

## 2. The resolution ladder (reuse `app/commission/resolver.py`, don't rebuild)

`resolver.py` already has `_match_by_mbi`, `_find_name_dob_match` (confidence-scored), and
`_enqueue_suggestion`. Recovery is mostly *applying* this machinery.

Per item, highest-confidence first:

1. **MBI exact** → auto-apply. Zero ambiguity.
2. **member_id / carrier_member_id exact** → auto-apply. A real carrier ID is as good as an MBI.
3. **Strong composite** — name + DOB + **at least one** corroborating field (zip, phone,
   email, or address) all agree → auto-apply. Requires extending `_find_name_dob_match`
   (today name+DOB only) to demand a corroborating field for the auto-apply tier.
4. **Weak composite** — name + DOB only, OR name + one field but not the full set → **queue
   for AJ**, confidence-scored, never auto-applied.
5. **Name alone / no match** → queue, flagged "insufficient identity / no candidate."
   **Name alone is never sufficient** to match or to write.

**Stop rule:** the engine writes only on tiers 1–3 (a real ID, or a corroborated composite).
Anything weaker is a *suggestion*, never a silent write. Name-alone never matches.

**When a stub IS resolved (tier 1–3 auto, or AJ-confirmed):** re-point its
`CommissionLineItem.customer_id` to the real customer, then **delete the fake
`uhc::0::N` Policy row**. The payment lives in the ledger; the placeholder policy is gone.
Book counts clean up automatically.

## 3. Name recovery (Link 2) — ledger-first

BOB source files are **deleted after parsing** (`upload.py` `os.remove`), so we cannot rely
on a retained file archive. Recover names in this order:

1. **Ledger (primary, in-DB, reliable):** for each no-name policy, find a
   `CommissionLineItem` matching by MBI or member_id carrying a `member_name`
   (we confirmed many line items carry "LAST, FIRST"). Parse → fill
   `first_name`/`last_name`/`full_name` on the policy AND its linked customer if also
   blank. Auto-applies (exact ID match = tier-1 confidence).
2. **Leftover files (secondary):** a pass over source files that DO still exist
   (`instance/uploads/` leftovers + `docs/Commission DL/`), matched by member_id.
3. **Queue (remainder):** still nameless → Needs Identity hub. Never invented.

**Safety:** never overwrite an existing name; never touch a `manually_edited` customer's
name (consistent with upload rules). The 7 no-name policies whose customer already has a
name are the trivial copy customer→policy.

## 4. AOR interval recovery (Link 4) — auto-derive from policy facts

For each agent'd customer with no `CustomerAorHistory` interval, **derive** one from its
policy — agent + carrier + `effective_date` + (`term_date` end, `None` for BCBS) — exactly
as `customer_set_agent()` already does on assignment. **The carrier-provided start/end dates
on the policy are the source of truth** (this is what the agency already treats as
authoritative; we do not invent or shift them). Auto-applies where the policy carries
the facts. A customer whose policy LACKS `effective_date`/`carrier` (can't derive) → Needs
Identity hub ("needs AOR interval"). Idempotent (skip if an equivalent interval exists).
This likely clears most of the 2,353 automatically.

## 5. The Needs Identity hub — repurpose `/customers/unassigned` (NO new page)

Per Tim: do not add another page/layer. **Repurpose the existing
`/customers/unassigned`** (`customers_unassigned` in `app/customers.py`), which already does
the show-known-data + suggested-match + one-click-resolve pattern, into the broader
**Needs Identity hub**. Broaden it from one category to four, via a category filter/tabs on
the SAME page:

- **Needs agent** — today's behavior (the 38). Keep `_suggested_agent_id` + `customer_set_agent`.
- **Needs match** — NULL-customer payments (428) + the 51 stub payments. Each row carries
  ALL the info a human needs to attribute correctly (carrier, member name as written,
  amount, period, writing agent, source) + a suggested customer + confidence + confirm.
  A row may resolve to "match an existing customer" OR "create a new customer" — the human
  decides when the identity was too weak for the engine to auto-create.
- **Needs name** — no-name policies recovery couldn't auto-fill.
- **Needs AOR interval** — agent'd customers whose policy lacked facts to derive an interval.

Each row: what IS known (carrier, amount, member_id, source, date) + best-guess suggestion
+ confidence + one-click action (confirm match / recover / assign / mark resolved). Nav
badge = total open count across categories; goal is to work it to **zero**. The metrics-round
"Unattributed Policies" view folds in here (delete-don't-orphan the redundant page).

**Items in the hub are EXCLUDED from book/metric counts** (via `app/metrics.py`) until
resolved — so a blank record never silently inflates an agent's number — but they are never
deleted or hidden.

## 6. Prevention (stop the gaps refilling)

Creating a new customer/policy from a commission row is **intended and correct** for a
genuinely new-to-Medicare member (no existing customer should match — that's a real new
enrollment, not an error, and must flow without manual clicks during AEP). The problem is
only the *ambiguous* case: a row that doesn't match but might be an existing customer we
failed to match (which is how the `uhc::0::N` name-only stubs were born). So the rule is a
**confidence boundary, not "never create":**

- **Commission ingest — strong identity → CREATE:** an unmatched row that carries a
  **strong identity** (MBI, carrier ID, or a full composite name+DOB+zip-or-phone) is
  confidently new → create the new customer + policy as today. We can trust it isn't a
  duplicate of someone we already have.
- **Commission ingest — weak identity → HUB (no phantom policy):** an unmatched row with
  only a **weak identity** (e.g. name + amount, no MBI/DOB/corroboration) records the
  payment in the ledger and **enqueues a Needs-match item with ALL the info a human needs
  to attribute it** (carrier, member name as written, amount, period, writing agent, source
  file) — and does **NOT** create a phantom `uhc::0::N` Policy. AJ decides "new customer"
  vs "match existing."
- **BOB import:** an import that would create a no-name policy gets flagged into the hub
  rather than landing silently in the book.

The four-link guarantee is the durable contract; this boundary keeps it true going forward
without blocking legitimate new enrollments.

## 7. Components (small, mostly reuse)

- `app/identity.py` — **new.** The resolution-ladder orchestrator: `resolve_identity(record)`
  applying the MBI→member_id→name tiers via `resolver.py`'s matchers. One clear seam,
  independently testable.
- `scripts/recover_policy_identity.py` — **new.** One-time cleanup, dry-run default,
  `--apply`, idempotent, DB-backup-first. Runs the ladder over the 51 stubs + 103 no-name
  policies + 428 NULL-customer payments; auto-applies exact (re-point line item + delete
  stub; fill names from ledger); enqueues the rest.
- `scripts/recover_aor_intervals.py` — **new.** One-time Link-4 derivation, dry-run default,
  `--apply`, idempotent. Derives intervals from policy facts; queues the underivable.
- `app/customers.py` — broaden `customers_unassigned` into the 4-category hub; reuse
  `_suggested_agent_id`; add `_suggested_customer_match` (wraps resolver) + a confirm-match
  action.
- `app/metrics.py` — exclude hub-queued items (and any residual stub `member_id LIKE
  'uhc::%'` until cleanup deletes them) from book counts, so a blank/unresolved record
  never inflates an agent's number (small filter; the single-source guard test stays green).
- `app/commission/` ingest — prevention (§6): unmatched row → ledger + queue, not a fake Policy.
- Fold the metrics-round "Unattributed Policies" view into the hub.

## 8. Cleanup execution (live, money-adjacent → careful)

DB backup → dry-run each script (review the auto-apply vs queue split) → `--apply` →
verify on Postgres:
- stub `uhc::0::N` policies gone; **Tim's UHC ≈ 262**;
- no-name active policy count → near 0 (remainder in hub);
- NULL-customer agent_commission/chargeback payments → near 0 (remainder in hub);
- agent'd customers without an AOR interval → near 0 (remainder in hub);
- the book invariant holds (Σ agents + queued = total); hub count is the single
  "work-to-zero" number.

## 9. Testing

TDD on `app/identity.py`: each ladder tier; the auto-apply-exact / queue-fuzzy boundary;
the re-point-then-delete-stub behavior; name recovery never overwriting an existing name or
a `manually_edited` customer; AOR-interval derivation matches `customer_set_agent`'s logic
+ is idempotent. The existing `app/metrics.py` guard test stays green. Money-adjacent
cleanup verified on real Postgres, not just SQLite (per project discipline).

## 10. Acceptance criteria (the four links, restated)

After cleanup + with prevention live, for the agency's records:
1. Every `CommissionLineItem` has a `customer_id` OR is a tagged non-customer payment OR is in the hub.
2. Every active `Policy` has a name + member_id OR is in the hub.
3. Every `Customer` has a `primary_agent_id` OR is in the hub.
4. Every agent'd `Customer` has a dated `CustomerAorHistory` interval OR is in the hub.

The hub is the one place every exception lives, with a path to zero. Nothing blank,
nothing untraceable, nothing silently counted.

## 11. Out of scope (tracked)

- Carriers & Plans module **visual rebuild** (big-data-first drill-down, brand colors) — next spec; consumes clean data.
- Round 2 date-aware BOB↔commission reconciliation engine.
- Retaining BOB source files going forward (a storage/PHI decision; ledger-first recovery makes it non-blocking).
