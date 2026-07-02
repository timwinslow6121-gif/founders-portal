# Customer Name Normalization + Preferred Name + Duplicate-Merge UI

**Status:** Brainstormed + approved 2026-07-02. Ready for writing-plans.
**Origin:** Item-2 (no-MBI merge) shipped, but "John Couchell ×4" didn't collapse —
his 3 stubs are `name_only` (no DOB/MBI/shared-id) so they can't auto-merge, AND the
duplicate view can't reliably *find* them because customer names are stored
inconsistently. Tim: "we need a robust customer database … no conflicting, missing, or
segmented data." This spec fixes the **name** dimension and maps the rest.

**Legal name ≠ what we call them.** Two distinct concepts the current schema conflates:
- **Legal/carrier name** (`first_name`/`last_name`/`full_name`) — what CMS/the carrier
  has (e.g. *Donald Horstmann*). Used for dedup, MBI matching, official/compliance
  documents. Agents can CORRECT it (carriers send typos/wrong first names).
- **Preferred "goes-by" name** (`preferred_name`, NEW) — what the human wants to be
  called (e.g. *Craig* — a middle name, a nickname like Bob for Robert, a shortened
  form). Used for ALL conversational touchpoints: SMS, email, letters, greetings.
  Blank → fall back to the legal first name.

So *Donald "Craig" Horstmann* appears as **Donald Horstmann** on the enrollment record
but **"Hi Craig"** in a text.

## Problem (quantified on prod 2026-07-01, 5,146 customers)

Customer names are stored in incompatible shapes because ~7 code paths write
`full_name` independently:
- **496** rows where `full_name` ≠ `first_name + last_name` (denormalization drift).
- **313** ALL-CAPS `full_name` (e.g. `COUCHELL, JOHN`).
- **252** `LAST, FIRST` comma shape.
- **44** blank/empty `first_name` — the name lives ONLY in `full_name` (commission stubs).

Consequences: duplicate detection and portal-wide search can't match `COUCHELL, JOHN`
to `John Couchell`; labels/recap/AOR show inconsistent names. **Grounding case — John &
Aphroula Couchell (a couple), each split into 4 rows:**
- John: real `1366` (`John Couchell`, MBI, DOB 1955-09-08) + stubs `4241/4245/5964`
  (`COUCHELL, JOHN`, blank first/last, no DOB, no MBI, no line-item `carrier_member_id`;
  their policies are synthetic `uhc::0::N` placeholders — no shared real id).
- Aphroula: real `1365` + stubs `4240/4244/5961/5963`.

The stubs are `name_only` (no corroborating id), so item-2's cleanup correctly did NOT
auto-merge them — that's the safety gate, not a bug. They need a human, but a human
can't find/confirm them until the names are consistent and the merge UI shows enough
context.

## Goal

Two phases, sequenced. Phase 1 makes names consistent (so detection + search work and
stay working); Phase 2 gives a human a real review-and-merge surface for the
`name_only` clusters Phase 1 exposes.

## Decided behavior (Tim, 2026-07-02)

- **Order:** normalize names FIRST, then build the merge UI on the clean data.
- **Backfill scope:** normalize every customer EXCEPT `manually_edited=True` (respect the
  human-wins provenance rule).
- **Backfill safety:** dry-run report (`old → new` for every change) → Tim reviews →
  `--apply` on a backed-up DB. Idempotent.
- **Merge UI:** extend `/admin/customers/duplicates` with rich per-row context
  (name, DOB, MBI, policies/carriers, source, agent), pick keeper, confirm-same-person
  for `name_only`, merge via the existing `merge_customers` engine.
- **Durability (fold in):** (1) `full_name` is kept **in sync** with first+last at write
  time so the drift can't silently return — this is NOT a freeze: humans edit
  first/last/preferred freely and always win; the event only mirrors `full_name` to the
  parts. (2) the storage normalizer and the dedup matcher are made consistent so every
  *visible* cluster is actually *mergeable*.
- **Preferred name:** ONE `preferred_name` column (the goes-by). Conversational
  addressing uses `preferred_name` if set, else legal `first_name`. Always editable;
  legal name unchanged by setting it.
- **Legal-name edits:** an agent may correct the legal first/last anytime (sets
  `manually_edited=True`, respected by future imports). The durability event NEVER blocks
  or reverts a human edit — "derived" means `full_name` mirrors the parts, not frozen.

## Architecture

### Phase 1 — Name normalization

**Reuse `app/names.py normalize_person_name(raw) -> (first, mi, last, full)`** — already
parses every shape found (`COUCHELL, JOHN`→`John Couchell`, `BRYANT D,KATHERINE`→
`Katherine D. Bryant`, `john smith`→`John Smith`). No new parser.

**1a. Backfill script — `scripts/normalize_customer_names.py`**
- Dry-run default; `--apply` writes; DB backed up first; idempotent (2nd run = no-op).
- For each `Customer` where `manually_edited` is False:
  - Pick the best source: if `first_name`/`last_name` are populated and already clean,
    recompute `full_name` from them; if `first_name` is blank, parse `full_name` via
    `normalize_person_name` to recover first/mi/last, then rebuild `full_name`.
  - **Middle initial:** `Customer` has NO middle-initial column (only
    `first_name`/`last_name`/`full_name`). `normalize_person_name` returns an `mi`; the
    backfill folds it into `first_name` as `"First M."` (e.g. `first_name="Jack J."`,
    `last_name="Winecoff"`), so `full_name` stays a pure `first + " " + last` derivation
    and no data is lost. Do NOT create a new column.
  - Write first/last/full_name only if any changed. Print `id: old → new`.
- `first_name`/`last_name` are provenance-tracked (`PROVENANCE_FIELDS`); the write goes
  through the provenance seam (or explicitly preserves trust) so a normalization
  reformat does not fabricate `human_verified` trust. (A reformat is not a human edit.)
- Report totals by shape fixed (caps / comma / blank-first / drift).

**1b. Durability — keep `full_name` in sync with parts at write time (NOT a freeze)**
Root cause of the 496 drift = `full_name` assigned independently at ~7 sites
(`customers.py:456`, `upload.py:215/318/496/528/764`, `commission/resolver.py:76/131/517`).
Add a SQLAlchemy `before_insert`/`before_update` event on `Customer` that, when
`first_name`/`last_name` are present, recomputes `full_name = f"{first} {last}".strip()`
(the middle initial rides inside `first_name` as `"First M."`, so it appears in
`full_name` automatically — no separate MI handling needed). This catches ALL write paths
without editing 7 call sites and makes first+last the source of truth for `full_name`.
- **This does NOT freeze names.** A human editing `first_name`/`last_name` (via the
  profile editor) is always allowed — the event simply keeps `full_name` matching the new
  parts. Legal-name corrections (carrier sent "Jon", it's "John") flow normally and set
  `manually_edited=True`, respected by future imports.
- Sites that assign `full_name=` directly for a **blank-first stub** keep working (the
  event only overrides when first/last are present).
- Tradeoff (intended): `full_name` is no longer independently authoritative — it mirrors
  the parts. `preferred_name` (1d) is where "what we call them" lives, so nothing
  conversational is lost by making `full_name` a legal-name derivation.

**1c. Normalize-on-write going forward (BOB path)**
Confirm the BOB upsert (`_upsert_customer_from_policy` in `upload.py`) routes parsed
names through `normalize_person_name` like the commission path does (item-1). If not,
wire it so new BOB rows land canonical. (Verification task; wire only if a gap exists.)

**1d. Preferred "goes-by" name (`preferred_name`) + one addressing helper**
- **Migration:** add nullable `Customer.preferred_name VARCHAR(128)`. NULL/blank = use the
  legal first name. Never written by imports — human-set only. Add to `PROVENANCE_FIELDS`
  so it's an editable, provenance-tracked profile field.
- **Profile editor:** a `preferred_name` input on the customer profile (inline-editable
  like the other fields), labeled e.g. "Goes by (preferred name)". Setting it does NOT
  touch the legal name.
- **ONE addressing seam — `address_as(customer) -> str`** (new, small helper, e.g. in
  `app/names.py`): returns `customer.preferred_name` if set, else `customer.first_name`.
  This is the single source of truth for "what do we call this person" so no touchpoint
  re-implements the fallback. Retrofit the **known** conversational touchpoints that greet
  by first name to call it: SMS send/templates (`app/comms/`), email greetings
  (`app/mailer.py` callers), letters/labels where a salutation is used. **Legal name
  stays** on the enrollment record, MBI matching, and any official document — `address_as`
  is ONLY for conversational greetings.
  - **Incremental adoption is expected.** We are NOT enumerating every greeting site up
    front — additional spots (call scripts, dashboard greetings, Retell/Quo-facing text,
    etc.) get switched to `address_as` as they're found while testing the portal. Because
    it's ONE helper, each retrofit is a one-line change (`customer.first_name` →
    `address_as(customer)`), not a redesign — this is the whole reason for the seam.
- **Display hint:** on the profile, show the legal name with the goes-by beside it when
  they differ (e.g. *Donald Horstmann — goes by "Craig"*) so agents see both at a glance.

### Phase 2 — Duplicate-merge review UI

Extend `/admin/customers/duplicates` (already renders item-2's
`find_no_mbi_clusters`). For each cluster:
- Show **rich per-row context** so a human can judge `name_only` clusters: display_name,
  DOB, MBI (or `—`), policy count + carriers, `source`, `stub`, primary agent.
- Keeper pre-selected to the most-complete row; reviewer can change it.
- `name_only` → a REQUIRED "confirm these are the same person" checkbox before submit;
  `conflict` → blocked; `dob_match`/`shared_id` → normal (unchanged from item-2).
- Merge posts to the existing `customer_merge` route → `merge_customers` engine.

After Phase 1, the Couchell rows normalize (`COUCHELL, JOHN`→`John Couchell`), cluster
cleanly, and become a ~2-click merge each.

**`preferred_name` in the merge:** add `preferred_name` to `merge_customers`'
fill-blanks-only field list so a keeper missing a goes-by inherits one from a loser (a
human-set preferred name must never be lost in a merge). Fill-blanks-only still applies —
an existing keeper preferred_name is never overwritten.

### Durability #2 — matcher/storage normalizer consistency
Storage uses `normalize_person_name` (First MI. Last); the matcher `find_no_mbi_clusters`
uses `integrity._norm_name` (lowercase, punctuation-stripped, token-SORTED). These serve
different purposes and can stay separate, BUT add a test asserting they agree on the
identity question for the known shapes (a cluster the human can SEE must be one the
engine can MERGE — no edge case where normalized-storage and normalized-matching
disagree such that a rendered cluster fails to merge).

## What this does NOT cover — the rest of the "robust database" goal (owned elsewhere)

This spec fixes the **name** dimension (format + segmentation-by-name). The broader
"no conflicting / missing / segmented data" goal spans systems already built:
- **Conflicting cross-field data** (two records disagree on DOB/phone/address) →
  the **provenance engine** (`app/customer_provenance.py`: manual>real>stub, conflict
  flagging). Our merge's fill-blanks-only AVOIDS creating conflicts; it does not RESOLVE
  pre-existing ones — that's provenance + remediation-roadmap work.
- **Missing data / broken links** → the **radar** already counts them:
  `payment_without_customer` (88), `no_name_policies` (56), `plan_id_orphans` (4611) =
  remediation-roadmap **items 3–4**.
- **Segmentation beyond names** → the **`uhc::0::N` synthetic stub policies** (the
  Couchell root cause) are a known separate population; name-normalization won't dissolve
  them. The real fix = match those commission rows to real customers (existing BACKLOG
  item: "51 `uhc::0::N` synthetic stub policies").

Documenting this keeps the project shippable while making the whole picture visible.

## Testing

- Normalizer backfill: unit tests per shape (ALL-CAPS, `LAST, FIRST`, blank-first via
  full_name, already-clean = no-op), idempotency, `manually_edited` skipped.
- Durability event: setting first/last recomputes full_name; a blank-first stub keeps its
  full_name; a human editing first_name updates full_name (edit NOT blocked/reverted);
  two write paths both produce consistent full_name.
- `preferred_name` + `address_as`: `address_as` returns preferred_name when set, legal
  first_name when blank; setting preferred_name doesn't change the legal name; a
  conversational touchpoint (SMS/email/label greeting) uses `address_as`; merge inherits a
  loser's preferred_name into a blank keeper (fill-blanks-only, never overwrites).
- Matcher/storage consistency test (durability #2).
- Merge UI: a `name_only` cluster renders the context fields + gated confirm-merge;
  engine already tested (item 2).
- Real-Postgres dry-run → Tim review → `--apply`, then spot-check search + the Couchell
  cluster collapses.

## Definition of done

- `scripts/normalize_customer_names.py` (dry-run→apply) canonicalizes all non-manual
  names; the 496 drift / 313 caps / 252 comma / 44 blank-first rows resolve.
- `full_name` stays in sync with parts at write time (drift can't silently return);
  human legal-name edits still work.
- Migration adds `Customer.preferred_name`; profile editor sets it; `address_as` seam
  drives conversational greetings (preferred else legal first); merge preserves it.
- BOB path stores canonical names going forward.
- `/admin/customers/duplicates` shows rich per-row context + gated `name_only` merge; the
  Couchell couple is mergeable to two clean profiles.
- Matcher/storage normalizer-consistency test passes.
- Opus whole-branch review (data path) + real-Postgres dry-run/apply + restart cycled.

## Explicitly deferred (YAGNI)

- **"Dismiss as not-a-duplicate"** record — so a reviewed false-positive cluster (e.g.
  the 3 different Connellys) stops reappearing. Tim chose the version without it; add
  later if re-review nagging becomes a problem.
- Merging multiple clusters in one action.
- Resolving cross-field conflicts / filling missing data (owned by provenance + roadmap).

## Reuse (don't rebuild)

- `app/names.py normalize_person_name` (the parser).
- `app/dedup.py find_no_mbi_clusters` + `app/customers.py merge_customers` (item 2).
- `app/customer_provenance.py` (provenance seam for the name write).
- The existing `/admin/customers/duplicates` route + template.
