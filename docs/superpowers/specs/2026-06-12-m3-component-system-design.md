# Material 3 Component System — Portal-Wide (Design / Spec)

**Date:** 2026-06-12
**Milestone:** 2 (UI/UX refinement) — supersedes the ad-hoc component direction; formalizes M3
**Status:** 📝 SPEC for Tim's review — NOT yet built
**Author:** brainstormed with Tim 2026-06-12

---

## 1. Context & goal

Tim's direction (stated mid-UI-refresh): **adopt Material 3 (M3) as the component language
for the entire portal.** Reference: https://developer.android.com/develop/ui/compose/documentation
(that's the Compose/Android spec; this portal is Flask + Jinja + vanilla CSS/JS, so "M3" here
means **CSS components that match the M3 visual spec + interaction model** — not importing Compose
or Material Web Components, which would add a build step / web-components dependency we don't want).

We already have a **Founders design system** (M2 Phase 1): tokens in `base.html :root` — blue
`#266EA5`, green `#65BB84`, Plus Jakarta Sans + Merriweather, radius 14/8, soft blue shadows,
light/dark via `[data-theme]`. M3 does NOT replace the brand; it **structures the components on top
of the existing tokens**. The pain points M3 fixes: native `<select>` stretches full-width (the
month picker bug), inconsistent inputs/buttons across 22 pages, and no shared interaction model
(focus rings, ripples, elevation).

**Principle:** keep the Founders palette + fonts; adopt M3's *component anatomy* (shape scale, state
layers, elevation levels, typography roles) and map them onto our tokens. M3 "primary" = Founders
blue; M3 "secondary"/"tertiary" = green/navy.

## 2. The M3 component library (Phase 0 — the foundation)

Build one CSS layer in `base.html` (so it's portal-wide), `m3-*` prefixed, theme-token-driven.
Components, in priority order (most-used first):

1. **Select / dropdown menu** (`.m3-select`) — outlined text-field style trigger + an anchored
   menu. Fixes the month-picker full-screen bug FIRST. Width = content, not full-bleed.
2. **Buttons** — filled (`.m3-btn`), tonal (`.m3-btn-tonal`), outlined (`.m3-btn-outlined`),
   text (`.m3-btn-text`). Map the existing `.btn-primary/.btn-secondary` onto these.
3. **Text field** (`.m3-field`) — outlined input with floating label, supporting/error text.
4. **Switch** (`.m3-switch`) — already built (the aggregate "Founders keep" toggle); promote it
   into the shared layer, retire the ad-hoc copy.
5. **Chips** (`.m3-chip`) — assist/filter/input chips (carrier filters, status tags).
6. **Segmented button** (`.m3-segmented`) — replaces the month/YTD pill toggle.
7. **Cards** (`.m3-card`) — elevated/filled/outlined; reconcile with the heavy existing `.card`.
8. **Dialog** (`.m3-dialog`) — replace `confirm()` calls + the modal patterns.
9. **Menu / list**, **tooltip**, **snackbar** (flash messages) — later.

### M3 tokens to add (mapped to existing Founders tokens)
- **Shape scale:** `--m3-shape-xs:4px --m3-shape-sm:8px --m3-shape-md:12px --m3-shape-lg:16px
  --m3-shape-xl:28px --m3-shape-full:999px` (our `--radius:14` ≈ md/lg).
- **State layers:** hover 8% / focus 10% / pressed 10% of the component's "on" color, via
  `color-mix`. One rule, applied consistently (replaces the scattered hover styles).
- **Elevation:** levels 0–5 → reuse `--shadow-sm/--shadow/--shadow-float` + 2 more.
- **Typography roles:** display/headline (Merriweather) · title/body/label (Plus Jakarta) — map to
  the existing 15px body / 12px floor scale from M2 Phase 1.
- **Motion:** standard easing + 180–250ms durations (the switch already uses ~180ms).

## 3. Adoption plan (phased — each phase shippable + verified)

- **Phase 0 — component layer** (this spec's core): build `m3-*` CSS in base.html + a living
  component-gallery page (`/admin/_m3` or a static doc) to eyeball every component in light+dark
  before adopting. Convert the **month picker → `.m3-select`** as the first real use (closes #1).
- **Phase 1 — commission module** (where we're actively working): recap, all-commissions, the
  adjustments + confirm-$0 forms, upload. Highest-traffic admin surface; we know it well.
- **Phase 2 — global chrome**: sidebar/topbar (already themed in M2 P1; re-skin nav items, the
  theme toggle → m3-switch).
- **Phase 3 — content pages top-down**: dashboard → customers → carriers/plans → settings → rest
  (mirrors the M2 Phase 2 order). Each page: swap inputs/buttons/cards to `m3-*`, drop its override
  CSS, verify light+dark.

Each phase: build → headless-render + live browser verify (light & dark) → deploy → next.

## 4. Non-goals / guardrails
- NOT importing Material Web Components or any JS framework — pure CSS + tiny vanilla JS (menu
  open/close, dialog focus-trap). Keeps the "vanilla JS only" rule.
- NOT changing the Founders palette or fonts — M3 is the *component* layer, brand stays.
- `labels.html` (print utility) stays excluded, as in every prior theme pass.
- Don't big-bang all 22 pages — phase it; the portal stays shippable throughout.
- Accessibility: M3 components must keep the global focus ring + real `<button>`/`<label>`
  semantics (no div-buttons).

## 5. Open questions for Tim
1. Component-gallery page: admin-only route (`/admin/_m3`) or a static HTML doc? (Route is easier to
   keep in sync with the live tokens.)
2. After Phase 0, is the priority **commission module first** (Phase 1) or **global chrome** (Phase
   2)? Spec assumes commission-first since that's the active work.
3. Dialogs: replace the browser `confirm()`s (e.g. "Confirm $0?", delete confirmations) with
   `.m3-dialog` in Phase 1, or leave native confirms until later?

## 6. Verification
- A component renders correctly in **light AND dark** (headless screenshot per component).
- The month picker no longer stretches full-width; opens an anchored menu.
- No regression: existing `.btn-primary`/`.card`/`.badge` keep working during migration (alias, not
  rip-and-replace).
- Per phase: the converted screens verified in a real browser before moving on.
