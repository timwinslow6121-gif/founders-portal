# UHC HRA Attribution + Edit-Preserve Fixes

_Date: 2026-06-26 · Status: diagnosed against LIVE production data + real code; spec ready.
**Do NOT build until the `feat/stub-creation-prevention` (item 1) branch is merged + deployed
AND AJ has finished his in-flight UHC manual edits** (don't stack unreviewed money-path
changes; AJ is editing live). Then build on its own branch, TDD, opus whole-branch review,
real-Postgres verify._

## Why this exists

AJ reported (2026-06-26): a UHC HRA payment for member **Luz Suarez** imported attributed to
**Rebekah at 55%**; AJ reassigned it to **Michael L.** via the Fidelity-view edit button. The
reassignment correctly removed it from Rebekah's recap, but on Michael's recap it showed as a
**Renewal** (not HRA) at **$27.50 with no Founders split**, instead of a **$50 HRA with
Michael's 52.5% split**.

The portal's own audit trail (`CommissionLineItemRevision`, the reason it exists) gives the
exact forensics. Revision id=37 on the Luz line (`uhc::0::568`):

```
before: {classification: "hra_bonus",       raw_amount: 50.0, split_rate: 0.55, agent_id: 4 (Rebekah), payment_type: "hra"}
after:  {classification: "agent_commission", raw_amount: 27.5, split_rate: 1.0,  agent_id: 7 (Michael), payment_type: "hra", manually_adjusted: true}
current sibling uhc::0::568::ovr: founders_override, raw_amount: 22.5
```

This decomposes into **THREE distinct bugs**. Fixing #1 (root) makes #2/#3 rarely matter,
because correctly-attributed HRAs won't need a manual edit at all.

## Bug 1 (ROOT) — UHC HRA rows attribute to the WRONG agent

**Symptom:** Luz's HRA went to Rebekah (agent_id=4) @0.55. Per AJ + Tim: the row's Writing
Agent ID **column C/col 5 cannot be trusted for HA/HRA rows** — it resolves to Rebekah (who
writes under the agency). The CORRECT agent ID is inside the **HA action string** (reported in
**column T**): e.g. _"HA payment for solicitor agent ID 6540381 for member LUZ SUAREZ MBI…"_.

**Root cause (confirmed in `app/commission/ledger.py`):** the code ALREADY knows the HA action
string names an agent — the comment at ledger.py:649-650 even shows it
(_"HA payment for agent ID 6337213 for member JEANETTE CATHCART MBI…"_) — but there is a
`_uhc_ha_member` regex (pulls the member name) and **NO `_uhc_ha_agent_id` regex** to pull the
agent ID. So HA/HRA rows fall back to the unreliable Writing-Agent-ID column → wrong agent +
that agent's split rate. The exact-parallel case for DVH rows is ALREADY handled correctly:
`_UHC_DVH_AGENTID_RE` (ledger.py:657) extracts _"written by 6435806"_ and attributes by it.

**Fix:** add `_uhc_ha_agent_id(action)` mirroring `_uhc_dvh_agent_id`, with a regex that
handles BOTH observed phrasings:
- _"HA payment for agent ID `<N>`…"_ (the in-code example)
- _"HA payment for solicitor agent ID `<N>`…"_ (AJ's May-file example)

i.e. roughly `r"\bfor (?:solicitor )?agent ID\s+(\d+)\b"` (case-insensitive). Then in
`extract_lineitems_uhc`'s attribution: for an HA/HRA row, if the action string yields an agent
ID, attribute by THAT id (through the same `writing_id_to_name` / ID→agent resolver the rest of
the loop uses), NOT the row's col-5 Writing Agent ID. Apply the resolved agent's contract split
rate (so Michael's 0.525, not Rebekah's 0.55). Quarantine only if the action-string agent ID
resolves to no contract (don't silently fall back to the wrong agent).

**Grounding:** re-importing May UHC must attribute Luz Suarez's $50 HA to Michael (the
solicitor in col T = 6540381 → Michael) at 0.525, classification `hra_bonus`, with no manual
edit required. **Verify against the real May UHC file** — confirm ALL HA rows pick up their
in-string solicitor agent ID, and the agency HA total is unchanged (only attribution moves).

**Out of scope:** changing how non-HA UHC rows attribute (col-4 Writing Agent ID is correct for
them — see ledger.py:570-571). This fix is HA/HRA-rows-only.

## Bug 2 — the edit button DESTROYS the HRA label (shows as "Renewal")

**Symptom:** after AJ's edit, the line shows under "Renewals" not "HRA".

**Root cause:** `edit_line_split` (ledger.py:1138) hard-codes
`line.classification = (CHARGEBACK if agent_amount < 0 else AGENT_COMMISSION)`. It throws away
the original `hra_bonus` classification. The recap labels groups by `classification`
(`_row_kind`, recap.py:87-91: `hra_bonus`→"HRA", else `agent_commission`→"Renewal"). So the
edit flips the label even though `payment_type` correctly STAYS `"hra"` (proven in the
after_json — the data still knows it's an HRA; only the classification was clobbered).

**Fix:** `edit_line_split` must PRESERVE an `hra_bonus` classification across an edit. Either:
(a) keep `line.classification` as `hra_bonus` when the line was `hra_bonus` before the edit (and
the edited amount isn't a chargeback), or (b) derive the recap label from `payment_type == "hra"`
as well as classification. Prefer (a) — keep classification truthful — but ensure HRA bonuses
still flow into payout (they're agent commission that splits; `_row_kind` already treats
`hra_bonus` as a paid group). A chargeback edit (negative) should still classify `chargeback`.

**Grounding:** editing an HRA line (reassign agent, same amount) keeps it under the **HRA** group
on the new agent's recap, not Renewals. Add a test: a `hra_bonus` line edited to a new agent
stays `hra_bonus`.

## Bug 3 — the edit form pre-fills the OLD agent's split

**Symptom:** AJ intended a Michael split ($26.25 agent / $23.75 override on $50) but the line
saved $27.50 / $22.50 — which is **Rebekah's 55/45 split of $50**. The two boxes correctly
summed to $50 and were accepted, so the edit engine behaved as designed; the problem is the form
HANDED AJ the prior agent's split as the starting numbers, and there's no recompute when he
changes the agent. (Note: Michael's 52.5% of $50 = $26.25; AJ's remembered "$26.65" was itself
slightly off — which is exactly why a manual recompute is error-prone and the default must be
right.)

**Design note (intentional, keep):** `edit_line_split` stores AJ's entered dollars as the FINAL
payout at `split_rate=1.0` (ledger.py:1117-1143) — this is deliberate so special cases stick
(e.g. Anjana keeps 100%). We do NOT change that. The two-box "agent $ + Founders override $ must
sum to the line's raw total" model is correct and stays.

**Fix (UX, scoped):** when AJ changes the agent in the edit form, **re-suggest** the split at the
NEWLY-selected agent's contract rate for that carrier — pre-fill agent box =
`round(raw_total × new_agent_rate, 2)`, override box = `raw_total − that`. AJ can still override
either box (the sum-to-raw guard stays). This is a client-side recompute on agent-change +
exposing each agent's carrier rate to the form; no change to `edit_line_split`'s storage
contract. For an HRA specifically, the suggested split uses the new agent's rate so Michael's
$50 HRA pre-fills $26.25 / $23.75.

**Grounding:** in the edit form, reassigning Luz's $50 line to Michael pre-fills $26.25 agent /
$23.75 override (52.5%); reassigning to a 55% agent pre-fills $27.50 / $22.50. AJ accepts without
hand-math.

## Sequencing / safety

- **Bug 1 alone removes most of the need for Bugs 2/3** (correct attribution → no manual HRA
  edit). Build order: **1 → 2 → 3.** 1 and 2 are the high-value, low-risk pair; 3 is a UX polish
  that prevents the wrong-split footgun on the edits that still happen.
- All three are parser/edit-form logic: **no migration**, fully testable against the real May UHC
  file + unit fixtures. Per protocol: TDD, opus whole-branch review (money path), DB backup,
  real-Postgres re-import verify, confirm `systemctl restart` cycled.
- **Re-import caveat interaction:** re-importing May UHC to apply Bug 1 will RE-PARSE the
  statement — which (per the standing BACKLOG gap) wipes AJ's manual_adjusted edits on that
  statement. So Bug 1's live application must be coordinated with the manual-edit-preservation
  work, OR done as a one-time re-import AFTER confirming AJ's edits are re-derivable (Bug 1 makes
  Luz auto-correct, so her edit becomes unnecessary). Capture AJ's current edits (the 10 UHC +
  2 Humana manual_adjusted lines) before any re-import. **This is the operational risk to flag at
  build time.**

## Files (expected; confirm at build)
- `app/commission/ledger.py` — add `_uhc_ha_agent_id` + use it for HA/HRA attribution
  (`extract_lineitems_uhc`); preserve `hra_bonus` in `edit_line_split`.
- `app/commission/recap.py` — (only if Bug 2 fix (b) chosen) label off `payment_type=="hra"`.
- the Fidelity-view edit template + its route (`commission_line_edit`, routes.py:1354) — Bug 3
  agent-change recompute + expose per-agent carrier rates.
- Tests: HA-agent-ID extraction (both phrasings); HRA stays `hra_bonus` through an edit; edit-form
  suggested split uses the new agent's rate. Real-file verify on May UHC.
