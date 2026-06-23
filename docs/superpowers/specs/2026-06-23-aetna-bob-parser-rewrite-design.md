# Aetna BOB Parser Rewrite + Shared Name Normalizer — Design

_Date: 2026-06-23 · Status: approved, ready for implementation plan_

## 0. Why this exists

Round 1 (identity recovery) surfaced four hub issues. Diagnosis on live data traced
the two biggest — **Needs-agent** (Aetna customers with no suggested agent, dropdown
falsely defaulting to Anjana) and **Needs-interval** (Tim's Aetna customers with no
AOR interval) — to **one root cause: the Aetna BOB parser reads columns that don't
exist.**

Live evidence (2026-06-22): Aetna policies have **agent_id_carrier 0%** (vs UHC 95%,
Humana 90%), **effective_date 10%** (vs 99-100% everywhere else), **term_date ~1%**,
and malformed names. The parser looked for `First Name / Last Name / Agent ID /
Term Date` — none of which exist in the real Aetna BOB. The detection fingerprint is
also wrong (keys on a non-existent `Sales Event` column).

Tim's broader goal: **use BOB uploads to keep the portal as fresh as possible and cut
manual data entry.** So beyond fixing the breakage, this spec captures every useful
field the Aetna BOB carries.

## 1. The real Aetna BOB format (both upload paths)

Both Aetna BOB files share the same core columns **by name** (so a header-based parser
serves both — this is what lets AJ and agents both upload without breaking each other):

| Column | Agency-wide (AJ, June 18) | Per-agent (agent download, e.g. Tim May 6) |
| --- | --- | --- |
| `Medicare Number` | ✅ | ✅ |
| `Member ID` (the `NG…` id) | ✅ | ✅ |
| `Member Name` (`LAST [MI],FIRST`) | ✅ | ✅ |
| `Member State` | ✅ | ✅ |
| `Plan ID` (e.g. `H3146-006`) | ✅ | ✅ |
| `Coverage Period` | ✅ | ✅ |
| `Effective Date` | ✅ | ✅ |
| `Writing Agent Name` | ✅ "Long, Rebekah" | ✅ "WINSLOW, TIMOTHY" |
| `CMS New` (Y/N) | ✅ | ✅ |
| `Member Sig Dt` | ✅ | ✅ |
| `Payee Amount`, `1099 Year`, `Payment Date`, `Additional Payment Detail` (commission/tax — ignored) | ✅ (varies) | ✅ (varies) |

(`CMS New` and `Member Sig Dt` are present in both files; `CMS New` is captured (§3),
`Member Sig Dt` is deliberately dropped. The `Payee Amount`/`1099 Year`/`Payment Date`/
`Additional Payment Detail` columns are commission/tax data, not BOB customer data — ignored.)

There is **no Term Date column** in the Aetna BOB. Aetna's BOB is leaner than
UHC/Humana — **no DOB, phone, full address, or county** — so those cannot be filled
from it.

## 2. Scope

**In scope:**
1. Rewrite `app/parsers/aetna.py` to the real format, **header-based** (both files
   parse; extra columns ignored; trailing summary rows like `$202.44 x.55` skipped).
2. Fix the Aetna detection fingerprint in `app/upload.py` `_detect_carrier`.
3. Capture all useful fresh-data fields (§3).
4. Resolve the writing agent **by name** via the existing commission name-matcher (§4).
5. One shared **name normalizer** → "First MI. Last" proper-case, wired into Aetna (§5).
6. **Fill-blanks-only** write rule for BOB freshness (§6).
7. Re-import the Aetna BOB + verify on live Postgres (§8).

**Out of scope (logged as fast-follows):**
- Retrofit ALL other parsers (BOB + commission) to the shared normalizer + a one-time
  stored-name backfill to the "First MI. Last" standard. (Tim wants this everywhere;
  sequenced after Aetna establishes the normalizer.)
- The Needs-match agent-picker UI and the 40 stub-name fills (separate hub-polish items).
- Round 2 date-aware reconciliation.

## 3. Fields captured (Aetna → portal)

| BOB column | Portal field | Notes |
| --- | --- | --- |
| `Medicare Number` | `mbi` + `member_id` | identity key |
| `Member ID` (`NG…`) | `carrier_member_id` | **powers payment→customer matching (Link 1)**; column already exists on Policy |
| `Member Name` | `first_name`/`last_name`/`full_name` | via the shared normalizer (§5) |
| `Writing Agent Name` | `agent_id` (raw name) | resolved by name in the upload path (§4) |
| `Effective Date` | `effective_date` | fixes the Needs-interval gap |
| `Member State` | Customer `state` | currently blank for these |
| `Plan ID` (`H3146-006`) | `plan_name` → resolved to a Plan record + `plan_type` via the upload's existing `_plan_alias_map`/plan resolution |
| `Coverage Period` | `renewal_date` | current plan-year date |
| `CMS New` (Y/N) | `commission_type` | "Y"→`initial`, else `renewal` |
| `term_date` | **None** | Aetna BOB has no term column — explicit None, never guessed |

`Member Sig Dt` is **deliberately NOT captured** — no actionable use (doesn't drive
trends/forecasting/filtering); YAGNI.

All target columns already exist on `Policy`/`Customer` (`carrier_member_id`,
`renewal_date`, `state`, `commission_type`) — **no migration needed.**

## 4. Agent resolution by name

The Aetna BOB identifies the agent by NAME, not a writing-ID, so the ID-based
`resolve_writing_agent` cannot match. The parser places the raw `Writing Agent Name`
in the record; the Aetna upload path resolves it to an agent using the **existing
commission name-matcher** (`_normalize_name` + nickname dict in
`app/commission/routes.py`, already proven on "LAST, FIRST" + casing — handles both
"Long, Rebekah" and "WINSLOW, TIMOTHY"). An unresolved name falls to the Needs-agent
hub (correct — better than a wrong default). No new ID seeding.

## 5. Shared name normalizer

New shared seam `normalize_person_name(raw) -> (first, middle_initial, last, full)`
producing the **"First MI. Last"** proper-cased standard (reusing/extending the
existing `display_name()` from the commission Fidelity work, promoted to a shared home
— e.g. `app/names.py`). Handles the real formats:

- Aetna `Member Name` `"BRYANT D,KATHERINE"` → first="Katherine", MI="D", last="Bryant", full="Katherine D. Bryant"
- `"JAMES S,NAOMI"` → "Naomi S. James"
- Commission `"WINECOFF, JACK J."` → "Jack J. Winecoff"
- Plain `"First Last"` → proper-cased passthrough

Rules: split on the comma (last-side before / first-side after); a trailing
single-letter token is the middle initial; title-case each part; Mc/Mac + hyphen
best-effort (the documented `display_name` limitation, carried forward). Returns the
pieces so the parser stores `first_name`/`last_name` separately **and** a clean
`full_name`. **Wired into Aetna now; other parsers adopt it in the fast-follow.**

## 6. Fill-blanks-only write rule

In the customer/policy upsert, each captured field is written **only when the existing
portal value is blank**; a filled value is never overwritten by BOB. This makes a BOB
upload only ever ADD freshness, never destroy a correction or introduce stale-overwrite
drift (that nuance belongs to Round 2). `manually_edited` customers keep full PII
protection (existing rule). Identity (MBI/member_id), agent, and effective_date follow
the existing carrier-authoritative update path (these are the carrier's current truth
and already update today).

## 7. Detection fix

`_detect_carrier` (`app/upload.py`): the Aetna XLSX fingerprint becomes
`"medicare number" in headers AND "writing agent name" in headers` (both present in
both files). Remove the bogus `"sales event"` check. Keep ordering so it doesn't
mis-detect UHC/Humana (they lack `writing agent name` as a BOB header).

## 8. Re-import & verification

Re-import the Aetna BOB (files are in the repo under
`docs/Commission DL/_ARCHIVE_original_messy_files/Commission docs/`). Verify on live
Postgres:
- Aetna `agent_id_carrier`/`agent_id` resolves to real agents (was 0%);
- `effective_date` populated (was 10%);
- names are proper-cased "First MI. Last";
- `state`, `plan_name`/`plan_type`, `renewal_date`, `commission_type`, `carrier_member_id` filled;
- the Needs-agent + Needs-interval **Aetna** hub entries clear (the 38 needs-agent are
  Aetna; the 3 needs-interval are Tim/Aetna);
- fill-blanks-only confirmed (a re-import doesn't overwrite a non-blank field).

## 9. Testing (TDD)

- **Parser:** both real files as fixtures (agency-wide + per-agent) → assert
  agent name, effective_date, first/last/full name, carrier_member_id, state, plan,
  renewal_date, commission_type all populate; trailing summary row skipped; term_date None.
- **Normalizer:** unit tests for each §5 format → "First MI. Last".
- **Fill-blanks-only:** a customer/policy with a non-blank field is NOT overwritten by a
  BOB value; a blank field IS filled.
- **Detection:** both Aetna files detect as "Aetna"; a UHC/Humana header does not.
- **Real-Postgres verify** on re-import (per project discipline for data-path changes).

## 10. Acceptance criteria

After the rewrite + re-import: every Aetna active policy has a resolved agent (or sits
in the hub), an effective_date, a proper-cased name, and the captured freshness fields;
the Aetna-rooted Needs-agent and Needs-interval hub entries are cleared; both AJ's
agency-wide file and the per-agent file parse through the same parser; no existing
non-blank data was overwritten.
