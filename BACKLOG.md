# Founders Portal — Live Backlog

> **The single source of truth for what's open.** Keep it clean: when something
> ships, move it to "Recently shipped" (then prune after a week); when something
> breaks, log it under "⚠ Regressions" so a side-effect is never lost. Updated
> every session (see CLAUDE.md → Session Protocol).
>
> **Legend:** ⬜ open · 🟡 in progress / partial · ⏸ deferred (with trigger) · ⚠ broken/regression
> **Priority:** 🔴 do soon · 🟠 important · 🟢 nice-to-have
> Add freely; one line each; link a spec/memory if one exists. Don't list speculative ideas here — those go in `docs/superpowers/Ideas/`.

_Last updated: 2026-06-17_

---

## ⚠ Regressions / broke recently
_Anything a recent change broke or left half-done. Clear these FIRST._

- ⬜ 🔴 **All-Customers search + filter bar do NOT filter (2026-06-17, Tim-reported).** In the All Customers module the search box and filter bar return wrong/unfiltered results — Tim couldn't reach Tocara Brown by search, had to navigate via Agent Commissions > Brian > Humana > chargebacks > click name. Repro + fix the customer list query/filters. (Not caused by Phase 1 — pre-existing.)
- ⬜ 🟠 **No breadcrumbs / "back to where I came from" (2026-06-17, Tim-asked).** Following Agent Commissions > Brian > Humana container > chargebacks > customer-name lands on the customer PROFILE whose only back-link is the Customers list — Tim wants to return to the page he came FROM (the commission drill-down). Add a breadcrumb trail or a contextual back-link (file-path-explorer style) on the customer profile + commission drill-down chain.
- ✅ FIXED 2026-06-13 — over-merging the commission nav removed the "Agent Recaps" entry, so AJ thought agent recaps were gone (they were reachable but not discoverable). Fixed: one **"Agent Commissions"** module = matrix overview (landing) + per-agent recaps (clickable agent names/cells + agent pills + back-link). Commit 2c7580c. _(Lesson: a nav-merge must confirm the removed item's destination stays DISCOVERABLE, not just functional — screenshot the nav after.)_

---

## 💰 Commissions
- 🟡 🔴 **June UHC Med-Supp override fix — code SHIPPED (commit 49ea2e4), AWAITING re-upload to verify.** AARP Med-Supp override pairs written by agents NOT on the old hardcoded LOA whitelist (Anjana/Brian — e.g. DEVA, PATEL, KENDALL) fell to quarantine instead of splitting into agent_commission + founders_override. Dropped the `_UHC_MEDSUPP_AGENTS` gate (the smaller-of-pair = override rule is structural, applies to any agent); a lone Med-Supp line still quarantines. 2 tests, suite 251. ⚠ **NOT yet verified on real data** — the June file (stmt 59) was imported under the OLD logic + isn't saved to disk; **AJ must re-upload June UHC**, then confirm DEVA/PATEL/KENDALL leave quarantine (`/admin/commissions/59/quarantine` badge drops). If they DON'T, my AARPMODMEDSUP plan_type assumption was wrong → need AJ's raw file to check col-12.
- ✅ **Commission-admin UX batch (2026-06-13→15) — all shipped + live:** #1 unresolved-stub-as-uploader fixed + 463 backfilled (460→Rebekah via root normalize_uhc-by-writing-ID fix, 3 unknowns) + **Unassigned Customers admin view** (nav badge, suggested-agent w/ basis, set-agent). #2 **All-Commissions = admin recap landing** (one "Agent Commissions" module). #3 **in-line quarantine resolver** (acea498). #4 **agent nav-bar** (persistent, fills row, responsive).
- 🟡 🔴 **commission→customer ENRICHMENT + AOR timeline reconciliation.** Spec: `docs/superpowers/specs/2026-06-16-commission-enrichment-aor-reconcile-design.md`. Grounding case Tocara Brown.
  - ✅ **Phase 1 SHIPPED + LIVE (2026-06-17, commit 439b911):** AOR reconcile — only ENROLLMENT rows open new intervals (any row bootstraps a customer's FIRST interval); a newer enrollment END-DATES older OPEN intervals for same (customer,carrier) at the row's term_date else **new_eff−1** (Medicare month-end). BCBS excluded. Backfill `scripts/backfill_reconcile_aor_intervals.py` (dry-run default, `--apply`, idempotent) **applied on VPS: 228 intervals closed** (220 = clean UHC annual plan-year rollovers e.g. 2025→12/31/2025; ~8 = mid-year re-enrollments incl. Tocara 3/1→5/31). Verified: 0 of 228 had an agent change (no cannibalization signal erased), Tocara now 1 open Humana interval, 2nd dry-run = 0 (idempotent), DB backed up pre-apply. 6 new tests, suite 249 green.
  - 🟡 🔴 **Phase 2 (PAUSED mid-design 2026-06-17 — resume here):** fill-blanks Policy/Customer (effective/term/plan/plan_type/commission_type) on create + crosswalk re-match, manual>BOB>commission, never overwrite, never touch manually_edited. **PLUS Policy supersession** (the part Phase 1 didn't fix — Tocara's Policy row still shows eff 3/1/active/no-term because Phase 1 only fixed the AOR-interval table, not the Policy table). **DECISIONS LOCKED with Tim:** (a) two policy rows — term the superseded enrollment + keep the new one as separate active row (NOT supersede-in-place); (b) this requires changing the policy crosswalk key from `(carrier, member_id)` → **`(carrier, member_id, effective_date)`** because Humana reuses the SAME member_id (800496116) for Tocara's 3/1 charged-back + 6/1 active enrollments. **Crosswalk match order designed (mid-brainstorm, Section 1 presented, awaiting Tim's OK):** 1) exact (carrier,member_id,eff)→adopt (idempotent; chargeback/renewal of same enroll); 2) no exact-eff but same (carrier,member_id) exists AND incoming is ENROLLMENT w/ later eff→create 2nd policy + term older at the AOR close-date; 3) renewal/chargeback w/ no exact-eff→adopt existing (don't branch); 4) nothing→create. ⚠ blast radius: changes the crosswalk EVERY carrier hits → must re-test idempotency + re-upload across all 6. Spec §4 Phase 2 + the Tocara grounding data (3 PolicyPayments: 2 chargeback eff 3/1 + 1 enrollment eff 6/1, none carry a Humana term_date so close-date derives to 5/31). Resume: finish presenting the design sections, get Tim's approval, then TDD.
  - ⬜ 🟠 **Phase 3:** extend MemberFact+normalizers for state/county/policy# + customer PII via the **provenance engine** (agent-fix>commission; first-look fills blank; conflict flags ONCE; agent-fixed→ignore commission; brand-new never-seen value→flag to call+confirm). [[customer-provenance-design]]
  - ⬜ 🟢 **Phase 4 (opt):** surface payment dates on profile (PolicyPayment already has them).
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
- ⚠ 🔴 **HTTPS cert expired 2026-06-16 → portal was DOWN (`ERR_CERT_DATE_INVALID`); FIXED same night.** Root cause: apt certbot crash-failed every auto-renewal because a pip-installed `cryptography 46.0.6` (leaked system-wide by our VPS `./venv/bin/pip install` runs) was incompatible with apt `pyOpenSSL 21.0.0` → certbot couldn't import. Fix: installed **certbot via snap (5.6.0)**, force-renewed (now valid → **Sep 14 2026**), reloaded nginx; `renew --dry-run` PASSES so auto-renew works. **FOLLOW-UPS (cert good 90d, not urgent):** (1) disable the old apt certbot + its `certbot.timer` so it can't conflict with the snap one; (2) **stop VPS deploys leaking `cryptography` into system Python** — the venv `pip install` isn't staying isolated (the original sin). Note: VPS commands that `pkill certbot` race against an in-flight renew — `certbot renew` applies a ~6-min random delay, use `--no-random-sleep-on-renew` for an immediate run.
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
- ✅ 2026-06-13→15 — Commission-admin UX: unassigned-customers fix+view, "Agent Commissions" unified module, persistent responsive agent nav-bar, in-line quarantine resolver.
- ✅ 2026-06-15 — Resolve quarantined payments from the matrix (pending badge → "N payments to review: $X" button → period-level review page, carrier-agnostic w/ carrier column + per-carrier breakdown).
- ✅ 2026-06-15 — Nameless+MBI-less UHC rows (DVH Manual Payment) are NON_CUSTOMER now (no junk stub); deleted the lone leftover. Unassigned customers = 0.
