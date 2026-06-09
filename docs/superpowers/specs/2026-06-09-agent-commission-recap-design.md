# Agent Commission Recap (R2) — Design Spec

**Date:** 2026-06-09
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the Commission Balancing System. Built on R1 (commission ledger, deployed) + R1.1 (Devoted two-file, deployed). This is the agent-facing payout view, with verifiability baked in.
**Related:** [[commission-balancing-system]], R1 spec `2026-06-08-commission-ledger-completeness-design.md`.

## Goal

Replace AJ's hand-made, emailed commission recaps with a live, in-portal, **agent self-service recap** that (a) shows each agent their monthly pay at a glance in plain language, (b) lets them **drill into the exact line items that prove the number is right** ("is AJ paying me correctly?"), and (c) keeps **all historical periods** for transparency. A period goes live only after AJ does his manual calcs (UHC) and **approves/publishes** it; the agent is then **notified**.

This is one cohesive feature: the interactive recap *and* the verifiability are the same page (drill-down = the proof).

## Users & access

- **Agent (self-service):** sees their **own** recap, all published periods, read-only. Nav item under "My Book" / "Commissions": **"My Commissions"** (or "My Recap").
- **Admin (AJ/Brian/Tim):** can view **any agent's** recap (agent selector), plus the **approve/publish** workflow and the **manual-entry** fields (UHC figure, optional prior-year baselines).
- Scoping: agent queries filter `agent_id=current_user.id, agency_id=current_user.agency_id` (the established pattern). Admin can pass an `agent_id`.

## The publish workflow (draft → approved → notify)

A given `(agent, period)` recap has a lifecycle:

1. **draft** — auto-assembled from the R1 ledger as commission files are uploaded. Clean carriers (Devoted/Humana/BCBS/Aetna/HealthSpring) populate automatically. **Not visible to the agent yet** (or shown as "pending").
2. **AJ's manual step** — AJ enters the **UHC** commission figure per agent (the number he calculates by hand today; R4 will automate it later), plus any corrections/overrides. UHC line is marked **"entered by AJ"** (provenance), distinct from ledger-derived carriers.
3. **approved/published** — AJ flips the period to published; this timestamps it and **notifies the agent** ("Your May 2026 commission recap is ready"). Now visible on the agent's self-service page.

New model `AgentRecapPeriod` (migration 024) holds this state: `(agency_id, agent_id, period_label, status ∈ draft|published, uhc_manual_amount, uhc_manual_note, published_at, published_by_id, notified_at, prior_year_total nullable)`. Everything else (per-carrier figures, line items) is **derived live** from `CommissionLineItem` — the period row only stores the workflow state + the manual UHC figure + optional prior-year baseline. (Keeps one source of truth; a re-upload re-derives instantly.)

## Data sources (every number, where it comes from)

- **Per-carrier commission + line items + split math:** `CommissionLineItem` (R1 ledger), filtered `agent_id`, period, carrier. `split_breakdown(line)` derives each line's `your_payout` (raw × split). Carrier total = Σ payouts. **No new commission math** — reuse R1's seam.
- **UHC:** until R4, `AgentRecapPeriod.uhc_manual_amount` (AJ-entered). Shown as a carrier card like the rest, tagged "entered by AJ."
- **New members (per carrier + total):** count of `agent_commission` line items classified as new enrollment (the ledger's payment_type / classification distinguishes new vs renewal), corroborated with `Policy.effective_date` in the period where available.
- **Lost members (per carrier + total):** `Policy` records where the agent was AOR (`primary_agent_id`) with `term_date` in the period and `status='termed'`, grouped by carrier. (Not from the ledger — from BOB/Policy data.)
- **% of book per carrier:** carrier's active member count / agent's total active members (from `Policy`/AOR, the same source as the existing "Client Count by Carrier").
- **YTD CY-vs-LY + per-month trend:** sum payouts by month for the current year (from ledger). Prior-year: use ledger data where it exists; else `AgentRecapPeriod.prior_year_total` if AJ entered it; else show **"no prior-year data"** (graceful — the system gets richer as years accumulate).
- **Run-rate ("On Pace For"):** simple projection — YTD payout ÷ months-elapsed × 12. Plain-English label + tooltip definition.

## Page architecture (single screen, no scroll, KISS)

One agent-facing page (`/commissions/recap`, admin `/admin/commissions/recap?agent_id=`), period selector at top. Three stacked tiers (locked in brainstorm):

### Tier 1 — Headline KPIs (three big centered cards)
- **Total Paid to You** — $ for the period.
- **New Members** — `+N` with sub-line "gained N · lost M · net ±X" (gradient accent card).
- **After Chargebacks** — net take-home (commissions − chargebacks), with ⓘ tooltip defining "chargeback." This is the honest bottom line the legacy Commission Audit can't show.

### Tier 2 — Per-carrier cards (grid)
One card per carrier: brand-colored header bar + logo chip (each carrier its own brand color — approximations now, exact hex a later polish item), big centered $ amount, "+N new members" (green) or "no new members" (muted), "X% of your book", "verify ›". **Click → drill-down (Tier 2b).** Small carriers show a flat line-item list; big carriers (UHC/Humana, 200+) use the grouped+search pattern below.

### Tier 2b — Carrier drill-down (the "prove the math" view) — **Option C**
Tapping a card **expands a panel in place** (no new page, no modal) showing:
- **Header:** carrier + period + the carrier total ($ payout, N members).
- **Summary-first, grouped by type:** group rows — "New enrollments · 7 · $X ›", "Chargebacks · 3 · −$Y ›", "Renewals · 204 · $Z ›". Each group **expands** to its line items. New + chargebacks (the meaningful, small lists) are glanceable; the large renewals group stays collapsed until expanded.
- **Persistent search box:** "Find a member" — filters across all the carrier's line items instantly (handles the "I'm checking the Johnson policy" case without scrolling).
- **Line item columns:** Member (links to customer profile), Type pill (New / Renewal / Chargeback — plain words, color-coded), **Carrier Paid** (raw_amount, ⓘ "full amount before your split"), **Your Split** (× 55%), **Your Payout**. Chargebacks render red/negative.
- **Reconciliation footer:** "Total — your [carrier] payout = $X", plus a green confirmation strip: "✓ these lines add up to $X — exactly what you were paid, straight from the carrier's file." This is the verifiability guarantee made visible.
- Expanding a big group lazy-loads/virtualizes its rows (don't render 200+ up front) and is itself scrollable within the panel.

### Tier 3 — YTD comparison strip (glanceable, no drill-down)
One strip: **This Year So Far** ($ vs last year), **Growth** (▲/▼ % — *correct* direction, fixing the buggy arrows in AJ's PDF), **On Pace For** (run-rate, ⓘ), and a small **monthly trend** mini-bar (tap → monthly YoY detail). Plain language only — the Q1 PDF's "rate-adjusted growth / true volume-driven growth" jargon is **cut**.

## Visual design (locked in brainstorm, from the Founders Kadence theme)

- **Fonts:** body **Plus Jakarta Sans** 1.25rem (wt 500); headings **Merriweather** (700/800). Add the Google Fonts import.
- **Palette (official, from `docs/kadence-theme-export.dat`):** primary blue `#266EA5`, green `#65BB84`, navy `#002E4D` (headings/ink), slate text `#2D3748`, muted `#718096`, borders `#CBD5E0`, blue-tint surface `#D5E4F6`, page bg `#F7FAFC`, card `#FFFFFF`; success `#13612E`, alert/loss `#B82105`, warning `#F7630C`. Green for positive money/growth, red for losses/chargebacks.
- **Material-3 professional (not whimsical):** 20px rounded corners, soft blue-tinted shadows, generous white space, big centered numbers (2–2.7rem, weight 800), one blue→green gradient accent card, hover-lift on carrier cards (transform/shadow, 150–300ms), count-up on KPI values (respect `prefers-reduced-motion`).
- **No naked acronyms:** any term (Chargeback, On Pace For, Carrier Paid) gets a dotted-underline + hover/tap tooltip. A small "What do these mean?" glossary link covers the rest.
- **This is the R2 flagship of a new look.** A full portal re-theme (all existing pages to this system) is a SEPARATE later project; R2 establishes the design tokens it will reuse. R2 ships with its own scoped stylesheet/`{% block styles %}` using these tokens; it does not yet alter `base.html` globally beyond adding the fonts.
- Accessibility: WCAG AA contrast, visible focus states, keyboard-navigable drill-down, `cursor:pointer` on clickable cards, SVG (not emoji) for any icon, mobile-responsive (cards reflow 3→2→1).

## Notifications

On publish, notify the agent their recap is ready. Reuse existing infra: **email via SendGrid** (a small `send_email` helper — none exists generically today; `labels.py` shows the SendGrid pattern to factor out), and/or an in-portal indicator (badge on the nav item / dashboard alert). `AgentRecapPeriod.notified_at` records it (idempotent — don't re-notify). Email content: plain, "Your [period] commission recap is ready — $[total]. View it here: [link]."

## Components / files (decomposition)

- `app/commission/recap.py` (new) — the assembler: given `(agent_id, agency_id, period)`, build a `RecapView` data object (headline KPIs, per-carrier blocks with grouped line items, YTD/trend/run-rate) from `CommissionLineItem` + `Policy` + `AgentRecapPeriod`. Pure-ish, testable. Reuses `split_breakdown`.
- `AgentRecapPeriod` model + migration 024.
- Routes (in `app/commission/routes.py` or a focused `recap` module): agent `/commissions/recap`, admin `/admin/commissions/recap`, admin **publish** action, admin **set UHC / prior-year** action, a JSON endpoint for lazy-loading a big carrier's group line items + search.
- `app/templates/commission/recap.html` — the single-screen page + drill-down partial, scoped styles using the new tokens.
- `app/mailer.py` (new, small) — `send_email(to, subject, html)` factored from the labels.py SendGrid usage; used by publish-notify.
- Tests: `tests/test_commission_recap.py` — assembler math (carrier totals reconcile to ledger, net-after-chargebacks, new/lost counts, YTD/run-rate, "no prior-year data" path), publish workflow (draft not visible, published visible + notified once), UHC manual figure shown + tagged, access scoping (agent sees only own).

## Boundaries (what R2 is NOT)

- NOT R4 (UHC auto-calc) — UHC is AJ-entered for now.
- NOT the full portal re-theme — R2 is the flagship; re-theme is later.
- NOT changing R1/R1.1 ledger logic or the legacy Commission Audit/Payment Ledger views (they coexist; the legacy Audit's positives-only gross is explicitly superseded by this view, per [[commission-balancing-system]]).
- NOT a balance/agency-P&L view (that's R3 — "do the books balance" across all agents + Founders keep).
- Per-carrier exact brand hex + Merriweather-on-numbers: polish items, not blockers.

## Open items (non-blocking)
- Exact per-carrier brand colors (approximations now).
- Whether notify is email, in-portal, or both (default: both, email primary).
- Prior-year backfill is optional/manual until ≥1 full year of ledger data accrues.
