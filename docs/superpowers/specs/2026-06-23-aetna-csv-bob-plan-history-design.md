# Aetna CSV BOB (MedicareApprovedBOBReport) + Plan-History from Terminations — Design

_Date: 2026-06-23 · Status: approved, ready for implementation plan_

## 0. Why this exists

The Aetna parser rewrite (2026-06-23) fixed the XLSX BOB and cleared the 46 members in
the April files — but 43 active Aetna policies stayed unattributed because they weren't
in any April file. AJ's current **June 18 export** (`Founders Insurance Agency
LLC_MedicareApprovedBOBReport_20260618.csv`) covers them — but it's a **different,
richer format** the current parser can't read.

This file is the freshness goldmine the April XLSX lacked: it carries **DOB, phone,
full address, term dates, and the Writing Agent NPN**. It also carries **138 termed
rows** with real term dates — and 26 of those members are still customers (9 switched
to another carrier), which lets us build the per-customer **plan-history timeline** Tim
wants ("Aetna Signature PPO 2024→2025, then Humana 2025→now").

## 1. The June CSV format

CSV. Columns used: `Medicare Number`, `Member ID` (NG…), `First Name`, `Middle Initial`,
`Last Name`, `Date of Birth`, `Phone Number`, `Address Line 1`, `Address Line 2`, `City`,
`State`, `Zip Code`, `Coverage Effective Date`, `Member Status` (A/T), `Term Date`
(sentinel `3000-01-01` = none), `Plan Name`, `CMS Contract Number`, `PBP Code`,
`Writing Agent NPN`, `Writing Agent First Name`, `Writing Agent Last Name`. (Many other
columns — Producer Levels, TINs, etc. — are ignored.)

Live shape (214 rows): **76 active (`A`)**, **138 termed (`T`)**. Of the termed: 23 are
still customers, 26 have an active policy now, 9 of those switched carriers; ~112 left
the agency entirely.

**Detection already works:** `_detect_carrier`'s `.csv` branch returns "Aetna" for
`Medicare Number` + `Member Status`. No detection change needed.

## 2. Scope

**In scope:**
1. Add a CSV-format branch to `app/parsers/aetna.py` (format-detect: `.csv` ext or
   `First Name` + `Writing Agent NPN` columns → CSV path; the existing XLSX
   `Member Name` path is untouched). One parser, two shapes (like Healthspring's two).
2. Capture all fields incl. the new freshness PII (DOB/phone/address).
3. Active filter: only `Member Status='A'` rows become active policies.
4. Termed-row handling (§4): term existing policies + record closed plan-history for
   existing customers; skip departed members.
5. Agent resolution: **NPN-first, name-fallback**.
6. Fill-blanks-only for all freshness fields incl. PII, respecting `manually_edited`.
7. Re-import the June file + verify.

**Out of scope:** changing the April XLSX path; the other parsers' freshness retrofit
(still the logged fast-follow); a new history UI (the profile already renders
`aor_history`).

## 3. Field mapping (active rows → policy rec)

| CSV column | rec field | Notes |
| --- | --- | --- |
| `Medicare Number` | `mbi` + `member_id` | identity key |
| `Member ID` (NG…) | `carrier_member_id` | captured in rec; Policy has no column → ignored (same as XLSX path) |
| `First Name`/`Middle Initial`/`Last Name` | `first_name`/`last_name`/`full_name` | proper-cased; `full_name` = "First MI. Last" (build directly from the separate columns) |
| `Date of Birth` | `dob` | **NEW freshness** (fill-blanks) |
| `Phone Number` | `phone` | **NEW freshness** (fill-blanks) |
| `Address Line 1` + `Address Line 2` → `address1`; `City`/`State`/`Zip Code` | `address1`/`city`/`state`/`zip_code` | **NEW freshness** (fill-blanks). **KEEP Line 2** — there is NO `address2` column, so fold Line 2 into address1 (e.g. "4908 Cameron Valley Pkwy, Apt 4") so no part of the address is lost; just Line 1 when Line 2 is blank. |
| `Coverage Effective Date` | `effective_date` | |
| `Term Date` | `term_date` | `3000-01-01` → None |
| `Plan Name` (+ `CMS Contract Number`+`PBP Code`) | `plan_name` (+ contract/pbp available) | |
| `Writing Agent NPN` | `agent_id` (the NPN) | NPN-first resolution (§5) |
| `Writing Agent First/Last Name` | `agent_name` | name fallback |
| `Member Status` | `status` "active" / "termed" | drives §4 |

All target columns exist on `Policy`/`Customer` (`dob`, `phone`, `address1` (Line 2 folded in), `city`,
`state`, `zip_code`, `term_date`, `renewal_date`, `commission_type`) — **no migration.**

## 4. Termed-row handling (`Member Status='T'`)

The parser emits a rec with `status="termed"`, the real `term_date`, the member's
MBI/member_id, carrier, and plan_name — but **does NOT create a new policy.** The upload
path handles a termed rec:

1. **Term an existing active policy:** if a matching policy exists (carrier+member_id, or
   MBI) and is active, set its `term_date` + `status='termed'` from the file (the carrier
   says they left → feeds the terminations view). Respect fill-blanks for term_reason etc.
2. **Record closed plan-history — existing customers only, ADD-ONLY:** if the member is
   already a `Customer` in the portal, write a **closed `CustomerAorHistory` interval** —
   `carrier="Aetna"`, `plan_name`, `effective_date` (the row's Coverage Effective Date),
   `end_date` (the row's Term Date — always set, this is a PAST chapter),
   `source="aetna_bob_history"`. This builds the "Aetna [plan] [eff]→[term]" entry the
   profile already renders.
   - **⚠ ADD-ONLY — NEVER overrides or supersedes current AOR.** This writes ONLY a new
     *closed* interval. It MUST NOT modify, end-date, or supersede any **open** interval
     (`end_date IS NULL` = the customer's CURRENT AOR). If a customer is currently active
     on Humana/UHC, that open interval is left completely untouched; we only append the
     past Aetna chapter. (This is the OPPOSITE of the identity-recovery supersession logic
     — no supersession here, ever.)
   - **Idempotent:** skip if an equivalent (customer, carrier, plan_name, effective_date)
     closed interval already exists.
   - **Agent for the interval:** resolve via NPN/name as in §5; if unresolved, use the
     customer's `primary_agent_id` (`agent_id` is non-nullable on the model).
3. **Departed members skipped:** a termed row whose member is NOT a customer is skipped
   entirely — no stub, no record (no profile to show it on; avoids ~112 junk records).

This reuses the existing `CustomerAorHistory` model and the profile's `aor_history`
display — we feed the timeline, we don't build a new one.

## 5. Agent resolution — NPN first, name fallback

```
resolved = resolve_writing_agent("Aetna", rec["agent_id"], agency_id)   # NPN (already seeded)
if not resolved and rec.get("agent_name"):
    resolved = _match_agent_name(rec["agent_name"])                      # name fallback
```

The CSV path puts the **NPN in `rec["agent_id"]`** (so the existing
`resolve_writing_agent(rec["carrier"], rec["agent_id"], …)` call in upload.py resolves it
by ID directly) and the **name in `rec["agent_name"]`**. The Aetna name-fallback added
last round already fires when `resolve_writing_agent` returns None — it must read
`rec.get("agent_name") or rec["agent_id"]` so it works for BOTH formats (the XLSX path has
no `agent_name`, so it falls back to the name it stored in `agent_id`). The Aetna NPNs are
already in the attribution map from the prior seeding, so NPN resolution works today.

## 6. Fill-blanks-only + manually_edited (write rule)

All freshness fields — DOB, phone, address1, city, state, zip, plan, renewal,
commission_type — are written **only when the existing portal value is blank**, via the
`_fill_if_blank` helper (built last round), and **never** for a `manually_edited`
customer's PII (the existing guard in `_upsert_customer_from_policy`). Identity (MBI/
member_id), agent, effective_date, and the termination (§4.1) follow the carrier-
authoritative path. BOB only ADDs freshness; newer-wins is Round 2's job.

## 7. Components

- `app/parsers/aetna.py` — add `_parse_csv_format(df)` + a shape check in `parse()`
  (`.csv` / `First Name` + `Writing Agent NPN` → CSV path). Active filter + termed-row
  rec emission live here; the upload path acts on `status="termed"`.
- `app/upload.py` — (a) the Aetna agent-fallback reads `rec.get("agent_name") or
  rec["agent_id"]`; (b) a small termed-rec handler (§4: term existing policy + write
  closed history for existing customers, skip departed); (c) confirm DOB/phone/address
  flow through `_fill_if_blank` + the `manually_edited` guard.

## 8. Testing (TDD)

Real June CSV as a fixture:
- active count = 76; termed rows do NOT create new policies;
- DOB/phone/address + agent (resolved by NPN) populate on an active row;
- term-date sentinel `3000-01-01` → None;
- a termed row whose member has an existing active Aetna policy → that policy
  term_date/status set;
- a termed row whose member is an existing customer → a closed `CustomerAorHistory`
  interval written (carrier/plan/eff/end); idempotent on re-run;
- **ADD-ONLY guardrail: a termed row does NOT modify/end-date any OPEN interval** — a
  customer with a current open (Humana/UHC) interval keeps it untouched; only the closed
  Aetna chapter is appended;
- Line 2 of the address is preserved (folded into address1, not dropped);
- a termed row for a non-customer → skipped (no policy, no customer, no interval);
- the April XLSX parser tests still pass (both formats coexist);
- fill-blanks-only: a non-blank DOB/phone/address is not overwritten; a `manually_edited`
  customer's PII is untouched.

Real-Postgres verify on re-import (per project discipline).

## 9. Re-import & verification

Re-import the June CSV on the VPS (DB backed up first). Verify:
- the 43 previously-unresolved active Aetna members now have an agent (resolved by NPN/
  name), plus DOB/phone/address/effective_date where the file provides them;
- Needs-agent / Needs-interval Aetna hub entries drop sharply;
- the 26 still-customer termed members show a closed Aetna interval in their profile's
  plan history (e.g. "Aetna Signature PPO [eff]→[term]");
- ~112 departed-member termed rows created no records;
- a second re-import is idempotent (no duplicate intervals, no overwrite of non-blank).

## 10. Acceptance criteria

After parser extension + re-import: the June CSV parses as Aetna; active members get
attribution + freshness PII (fill-blanks, manually_edited-safe); the remaining unresolved
Aetna hub entries clear; termed members who are still customers gain an accurate closed
plan-history interval on their profile; departed members create no junk; both Aetna
formats (April XLSX + June CSV) parse through the one parser; no migration.
