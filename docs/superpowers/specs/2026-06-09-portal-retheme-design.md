# Portal Re-Theme — Founders Look, Light + Dark (Design Spec)

**Date:** 2026-06-09
**Status:** Approved (brainstorm complete) — ready for implementation planning
**Part of:** the post-R2 polish batch. This is **Phase A** (the global re-theme); the agent recap page is already the reference look. Features #1 (upload checklist), #2 (recap pills), #3 (agency totals view) are separate specs that build ON this.

## Goal

Re-skin the entire portal (all 26 templates except the already-done agent recap) to the **Founders look** established on the recap page — blue/green palette, Plus Jakarta Sans + Merriweather, rounded corners, soft shadows, airy spacing — while keeping the system fully usable in **both light and dark mode** (device-default + manual toggle). Agents disliked the old Lux gold theme; this unifies the whole portal on the look they approved.

## Why this is tractable

The portal is **27 templates, all extending `base.html`**, and the theme is driven by **CSS custom properties in `base.html`'s `:root`** (~84 `var(--…)` usages across pages), with an existing `@media (prefers-color-scheme: dark)` override block using the **same token names** (`--ink`, `--surface`, `--gold`, `--ivory`, `--slate`, `--border`, `--font-serif`, `--font-sans`). So the bulk of the re-theme is **swapping token values**, not rewriting pages. Pages inherit automatically.

## Approach (locked in brainstorm)

- **Token swap + light polish** (not a full per-page redesign): swap the `:root` token values to the Founders palettes → instant portal-wide palette/font shift; then a light pass adding rounded corners / shadows / spacing where pages look flat. Deep per-page redesign only where a page is clearly broken.
- **Light AND dark**, both on-brand (palettes approved). **Device default + manual toggle that overrides and remembers** (localStorage, per-device, no DB).
- **Tokens promoted to `base.html :root`** as the single source of truth; the recap page consumes the globals (drops its scoped `--rc-*` duplicates, OR maps them to the globals — see §Recap reconciliation).

## The theming model

Three-layer cascade on `<html>`:

1. **Default = device preference.** Keep `@media (prefers-color-scheme: dark)` so a new visitor matches their OS.
2. **Manual override via `<html data-theme="light|dark">`.** When the agent clicks the toggle, set `data-theme` and persist to `localStorage['fp-theme']`. CSS: `:root` = light tokens; `@media (prefers-color-scheme: dark) :root` = dark tokens; **`:root[data-theme="dark"]` = dark tokens; `:root[data-theme="light"]` = light tokens** (the explicit attribute wins over the media query by specificity + source order).
3. **No-flash pre-paint script.** A tiny inline `<script>` in `<head>` (before CSS paints) reads `localStorage['fp-theme']` and sets `document.documentElement.dataset.theme` immediately, so there's no light→dark flicker on load. (Inline, synchronous, runs before body renders.)

Toggle persistence is binary light/dark (matches the brainstorm decision — "toggle overrides + remembers"). Clearing the stored value falls back to device preference; the toggle itself just flips light↔dark and stores the result.

## Token definitions (the swap)

Replace the Lux values in both `:root` blocks. **Semantic roles are preserved** (critical — per CLAUDE.md, `--ink` = background, `--ivory` = readable text; these flip between modes and templates depend on it). Mapping old→new:

**Light (`:root`):**
- `--ink` (page background) → `#F7FAFC`
- `--surface` (card) → `#FFFFFF`
- `--surface-low/mid/high/top` (elevations) → `#EEF3F8 / #E4ECF3 / #D9E4EF / #CBD5E0`
- `--gold` (accent) → `#266EA5` (Founders blue); `--gold-dim`/`--gold-muted` → darker blues `#1F5A85 / #2B6CB0`
- add `--green` → `#65BB84` (positive/success accent), `--green-dim` → `#13612E`
- `--ivory` (readable text) → `#1A202C`; `--ivory-bright` → `#002E4D` (navy, headings)
- `--slate` (muted text) → `#718096`
- `--border` → `#CBD5E0` (and an `rgba` variant for overlays)
- status: error `#B82105`, warning `#F7630C`, resolved/success `#13612E`, waiting keeps a jewel tone
- `--font-serif` → `'Merriweather', Georgia, serif`; `--font-sans` → `'Plus Jakarta Sans', -apple-system, sans-serif`

**Dark (`@media (prefers-color-scheme: dark) :root` AND `:root[data-theme="dark"]`):**
- `--ink` (page bg) → `#0E1726`
- `--surface` (card) → `#172338`; elevations `#1E2C44 / #243353 / #2B3D60 / #324872`
- `--gold` (accent) → `#4A9FD4` (brightened blue); dims `#3E86B8 / #2E6E9E`
- `--green` → `#7BD49B`; `--green-dim` → `#3E8E63`
- `--ivory` (text) → `#E2E8F0`; `--ivory-bright` → `#F5F8FB`
- `--slate` (muted) → `#8AA0B8`
- `--border` → `#24344D`
- gradient accent (New-Members style): light `linear-gradient(135deg,#266EA5,#65BB84)`; dark `linear-gradient(135deg,#2E6E9E,#4E8E6A)` (muted so it isn't harsh at night)

(Exact hex per the approved palette mock; the implementer copies these.)

## Shared design tokens / polish

- **Border-radius:** introduce `--radius` (cards 16–20px, controls 10–12px) and apply in the light-polish pass.
- **Shadows:** `--shadow` (soft, blue-tinted in light; deeper/darker in dark), `--shadow-sm`.
- **Fonts:** add the Google Fonts link for Merriweather + Plus Jakarta Sans to `base.html <head>` (the recap already added it — keep one link, deduped). Remove/replace the Noto Serif + Inter link.
- **Base font size:** body 1rem→ keep readable (the recap uses 1.25rem for its content; portal-wide we keep the existing base size to avoid reflowing every table — polish, not a global bump).

## Light-polish pass (per-page, targeted)

After the token swap, walk the 26 pages and apply ONLY where needed:
- Cards/panels/containers: ensure `border-radius: var(--radius)` + `box-shadow: var(--shadow)` + adequate padding (many already have card classes that now inherit the new tokens).
- Buttons: `.btn-primary` now blue, `.btn-secondary` outline — verify contrast in both modes.
- Tables (`.data-table`): readable row hover, borders via `--border`.
- **`login.html`:** update to the new palette (left panel `--surface`, right `--ink`); it's outside the sidebar so check it explicitly.
- **`labels.html`:** EXCLUDED — it's a print utility with intentionally hardcoded light colors (per CLAUDE.md). Do not touch.
- The agent **recap** page: reconcile (see below).
- Do NOT redesign layouts; just bring flat pages up to the rounded/soft/airy standard.

## Recap reconciliation

The recap page currently defines its own scoped `--rc-*` tokens. Two options, implementer picks the lower-risk:
- **Preferred:** keep the recap's scoped `--rc-*` block but redefine its values to **reference the new globals** (`--rc-blue: var(--gold)` etc.) so it auto-follows light/dark — the recap becomes theme-aware (it's currently light-only) with minimal change.
- The recap MUST now work in dark mode too (since the toggle is global). Verify the gradient card, drill-down, and carrier brand colors (which are fixed brand hex, intentionally mode-independent) all read in dark.

## The toggle (UI)

In `base.html` sidebar footer, near the user name / Sign Out: a small button with a sun/moon SVG (no emoji). `onclick` flips `data-theme`, saves to localStorage, swaps the icon. Keyboard-accessible (`<button>`, `aria-label="Toggle dark mode"`), visible focus. Reuses `--ivory`/`--surface` so it themes itself.

## Components / files

- **Modify** `app/templates/base.html` — the heart: swap both `:root` token blocks, add `[data-theme]` override blocks, add the no-flash pre-paint script, add the fonts link (dedupe), add `--radius`/`--green`/shadow tokens, add the sidebar toggle button + its small JS.
- **Light-polish edits** across the 26 content templates as needed (mostly nothing if they use `var(--…)` + existing card classes; targeted fixes where flat). `login.html` checked explicitly. `labels.html` untouched.
- **Modify** `app/templates/commission/recap.html` — point `--rc-*` at the globals; verify dark mode.
- No models, no migration, no routes (pure presentation). No new Python.

## Testing / verification

- **No automated UI tests** (it's CSS); rely on rendered verification (the established method): render representative pages (dashboard, customers list, customer profile, commission audit, recap, login) in BOTH light and dark via headless screenshot, eyeball contrast/readability, fix issues. Confirm: no light-on-light or dark-on-dark text (the `--ink` vs `--ivory` role trap), toggle flips + persists across reload (no flash), recap still correct in dark.
- Run the existing test suite to confirm no template renders break (`pytest` — templates render in route tests).
- Accessibility: WCAG AA contrast both modes, visible focus, toggle keyboard-operable, `prefers-reduced-motion` respected on the theme transition.

## Boundaries (what this is NOT)

- NOT features #1/#2/#3 (separate specs, built after, in this look).
- NOT a per-page layout redesign — token swap + light polish only.
- NOT touching `labels.html` (print utility).
- NOT a DB-stored preference — localStorage per device (brainstorm decision).
- NOT changing the recap's data/logic — only its theming.

## Open items (non-blocking)
- Exact elevation hexes can be fine-tuned during the polish pass against real pages.
- Whether to also bump base font size portal-wide (deferred — avoid reflowing tables now).
