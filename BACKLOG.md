# Founders Portal — Live Backlog

> **The single source of truth for what's open.** Keep it clean: when something
> ships, move it to "Recently shipped" (then prune after a week); when something
> breaks, log it under "⚠ Regressions" so a side-effect is never lost. Updated
> every session (see CLAUDE.md → Session Protocol).
>
> **Legend:** ⬜ open · 🟡 in progress / partial · ⏸ deferred (with trigger) · ⚠ broken/regression
> **Priority:** 🔴 do soon · 🟠 important · 🟢 nice-to-have
> Add freely; one line each; link a spec/memory if one exists. Don't list speculative ideas here — those go in `docs/superpowers/Ideas/`.

_Last updated: 2026-06-12_

---

## ⚠ Regressions / broke recently
_Anything a recent change broke or left half-done. Clear these FIRST._

- ✅ FIXED 2026-06-13 — over-merging the commission nav removed the "Agent Recaps" entry, so AJ thought agent recaps were gone (they were reachable but not discoverable). Fixed: one **"Agent Commissions"** module = matrix overview (landing) + per-agent recaps (clickable agent names/cells + agent pills + back-link). Commit 2c7580c. _(Lesson: a nav-merge must confirm the removed item's destination stays DISCOVERABLE, not just functional — screenshot the nav after.)_

---

## 💰 Commissions
- 🟡 🔴 **Commission-admin UX batch (2026-06-13, in progress):**
  - ✅ #1a/b — unresolved stubs no longer attributed to the uploader (AJ); 463 backfilled to "unassigned" (live).
  - ⬜ #1c — **"Unassigned customers" view + reassign-agent UI** (463 stubs now need a real agent set).
  - 🟡 #2 — make **All-Commissions the admin recap landing** (merge; kill AJ's empty "My Commission" shell for admins). *(in progress)*
  - ⬜ #3 — **in-line resolve quarantined UHC rows** (set agent + override + split right in the portal; no way to currently).
  - ⬜ #4 — agent picker: dropdown → **visible agent nav-bar** (1-click to an agent).
- ⬜ 🟠 **AJ signs off on a real UHC upload run** + the quarantine tab before UHC is system-of-record. — `[[uhc-parser-resume]]`
- ⬜ 🟠 **UHC "New" enrollment proration** — the last big quarantine chunk (~48 rows, mostly "New" months-remaining math, cols L/T/AA/AB). Needs a few worked examples from AJ. Irreducible until then.
- ⏸ 🟢 **Aetna Medigap supplement parser** — `aetnasupplement.zip` ($101.53, different `Commission Details` shape). Deferred; normal agent split applies when built. — `[[session-handoff-2026-06-11-commissions]]`
- ⬜ 🟢 **BCBS recap names don't hyperlink** — BCBS rows have no MBI, so the customer_id back-link can't match. Would need a carrier_member_id match path.
- ⬜ 🟢 **BCBS 27¢ rounding** across agents — essentially correct, low priority.

## 🎨 UI / UX
- 🟡 🔴 **Material 3 component system, portal-wide** — spec written (`docs/superpowers/specs/2026-06-12-m3-component-system-design.md`), AWAITING Tim's review + answers to its 3 open questions. Phase 0 = build the `m3-*` CSS layer + convert the month picker to an M3 select.
- ⬜ 🟠 **M2 Phase 2 — content-page refinement** (dashboard → customers → carriers → settings, top-down; each adopts the system tokens, drops override CSS). — `[[m2-phase2-resume-point]]`
- ⬜ 🟢 ~7 content pages have `input:focus{outline:none}` suppressing the global focus ring — drop when refining each.

## 🗄 Data integrity / attribution
- ⏸ 🟢 **#3 Agency-as-real-agent (full)** — only the read-only "Founders Agency" override row was built. Full version (admin@ as an Agent-Settings entry with NPN + per-carrier IDs + contracts) deferred unless real agency-NPN business starts landing as "(unattributed)".
- ⬜ 🟢 **Provenance Plans 2–5** (CMS sync retrofit + OTC/meals, editing UI, conflict queue, filter layer) — engine deployed, consumers not built. — `[[provenance-and-next-work]]`

## 🔒 Infra / backup / security
- ⚠ 🔴 **Off-site Google Drive backup is DOWN** — rclone uses the shared default OAuth client_id which Google throttles globally (`RATE_LIMIT_EXCEEDED`). Retry flags shipped but the durable fix needs a **private OAuth client_id in Tim's Google console** (~5 min). Steps: `scripts/RCLONE_OWN_CLIENT_ID.md`. On-box pg_dumps exist so data isn't at risk, but off-site is broken until done.
- ⏸ 🟢 **S3 — encryption-at-rest** — deliberately deferred; reactivation trigger = white-labeling. — `[[s3-encryption-preview]]`
- ⬜ 🟢 **S4 — optional pentest pass** (dep CVEs + `/security-review`) on the S0/S1/S2 stack.

## 🔭 Future / when-relevant
- ⏸ HealthSherpa + Google Meet Pub/Sub provisioning (external blockers, Phase 3.06).
- ⬜ Termination outcome tracker; dedicated AEP page; Medicare.gov annual plan refresh. — see `docs/superpowers/Ideas/BACKLOG-triaged-2026-06-03.md` for the fuller idea list.

---

## ✅ Recently shipped (prune after ~1 week)
_Keep this short — it's a confidence check that things landed, not a permanent log (CLAUDE.md Build Status is the permanent record)._

- ✅ 2026-06-12 — All-Commissions matrix (#6) + Founders-keep toggle + currency + carrier-status (received/confirmed-$0/pending) + persistent contracted-carrier containers + Founders Agency override row.
- ✅ 2026-06-12 — UHC attribute by Writing Agent ID (Rebekah's $7,447 book recovered); $0.26 PARTD → override; HA→HRA; $16 Humana (Betty/Riddle) fixed; GTL/Medico brand colors.
- ✅ 2026-06-12 — Reconciliation adjustments (per agent/carrier/period + note); recap customer-name hyperlinks.
- ✅ 2026-06-11/12 — UHC shipped live (normalized pipeline + quarantine tab) with 3 prod hotfixes (migration 026 truncation, no_autoflush re-upload, writing-ID attribution).
