# Milestone 2 / Phase 1 — Founders Design System + Login Rebuild (Design)

**Date:** 2026-06-11
**Milestone:** 2 (UI/UX refinement) — Phase 1 of N (the foundation; pages = Phase 2+)
**Status:** Design — approved, pending spec review → writing-plans
**Author:** brainstormed with Tim 2026-06-10/11

---

## 1. Context & goal

The 2026-06-09 re-theme set color **tokens** in `base.html` but never set the
**spatial/structural system** — so every page improvised. Diagnosis (grep across
`app/templates/`):
- `base.html` declares `--radius:16px` / `--radius-sm:10px`, but templates use
  **9 different hardcoded radii** (3/4/6/8/12/99/1px) — none the token values.
- **~20 ad-hoc font-sizes**, a huge cluster at **9–12px** (unreadable; Tim's
  "text too light/small" complaint).
- An **invisible-text bug**: `commission_ledger.html:42` active tab sets
  `color:var(--ink)` (the page-background color) as text.
- Component classes are heavily used but loosely defined: `.card`×153,
  `.badge`×169, `.btn-primary`×19, `.btn-secondary`×25, `.data-table`×17.

Tim's goal (the "rocking chair"): every proportion agrees, the whole thing feels
effortless and intentional, nothing snags the eye. Bad UI isn't one broken thing
— it's radii that disagree, uneven padding, a color that means two things. The
fix is a **design system**: decide the proportions once, apply them faithfully.

**Build ON the current Founders look** (blue `#266EA5` / green `#65BB84`, Plus
Jakarta Sans + Merriweather) — refine into a system, don't reinvent. Agents
already approved this look on the recap page.

## 2. Scope (decided with Tim)

Phase 1 = define the system in `base.html` + apply to the **global chrome**
(sidebar/topbar/base) + build the **new login** + verify light&dark. It does NOT
refactor the 22 content pages — that's Phase 2+ (each its own spec, top-down:
dashboard → customers → commission cluster [+IA overlap question] → settings →
rest), each verified before the next.

**Risk control (Tim's "without breaking more things"):** Phase 1 only *defines*
tokens + *applies* them to a small surface (base/sidebar/login). The other 22
pages keep working **because they reference the same token names** — only the
*values* shift, and the value shifts are non-breaking by nature (16px→14px
radius and 9px→12px font can't break layout; they only look better). Structural
page rewrites (the breakable kind) are deferred to Phase 2+, one page at a time.
So Phase 1 cannot cascade-break the portal. Every step is verified in browser
(light + dark) before moving on.

## 3. Tokens (into `base.html :root`, with dark override)

### Type scale (replaces ~20 ad-hoc sizes; 12px hard floor)
| Token | Size | Use |
|---|---|---|
| `--fs-display` | 30px | login title, big KPI numbers |
| `--fs-h1` | 24px | page headings |
| `--fs-h2` | 19px | section headings |
| `--fs-h3` | 17px | card titles |
| `--fs-body` | **15px** | default body (new baseline) |
| `--fs-sm` | 13px | secondary / labels |
| `--fs-xs` | **12px** | smallest meta — the FLOOR, nothing smaller |
| `--lh` | 1.5 | body line-height |

Weights: Merriweather 700/900 (headings), Plus Jakarta Sans 400/500/600/700 (UI).
Set `body { font-size: var(--fs-body); line-height: var(--lh); }` as the base.

### Radius scale (replaces the 9 disagreeing values)
| Token | Value | Use |
|---|---|---|
| `--radius` | **14px** (was 16) | cards, panels |
| `--radius-sm` | **8px** (was 10) | buttons, inputs, small controls |
| `--radius-pill` | 999px (new) | badges, tabs, chips |

### Spacing scale (4px grid — replaces improvised padding)
`--sp-1:4px · --sp-2:8px · --sp-3:12px · --sp-4:16px · --sp-5:20px · --sp-6:24px · --sp-8:32px`
Defaults: card padding `--sp-6` (24px), gap between cards `--sp-4` (16px), tight
element gaps `--sp-2/3`.

### Colors — UNCHANGED
Existing blue/green/navy/surface/status tokens stay (refining, not recoloring).
**Token NAMES are kept even where now-inaccurate** (`--gold` = blue across 26
templates; `--radius` was 16). Renaming = pure churn + regression risk for zero
visual gain. The refactor is "make templates USE the tokens," not "rename them."

## 4. Component rules — "soft & tactile" finish (reusable classes in `base.html`)

Decided once so pages stop improvising. All use the locked blue/green, 14/8/pill
radius, soft blue-tinted shadows.

- **`.card`** — `--surface` bg, hairline `--border` (visible in BOTH light & dark
  — fixes invisible-border cases), soft shadow, `--radius` (14), `--sp-6` padding.
- **Hover** (clickable cards/rows) — gentle lift: shadow grows + `translateY(-1px)`,
  **no layout shift** (no scale-transforms that reflow), + `cursor:pointer`.
- **Focus** — visible **2px blue focus ring** on interactive elements (keyboard a11y).
- **`.badge`** — `--radius-pill`, soft-tinted bg from the status colors
  (open/progress/waiting/resolved/error).
- **`.btn` / `.btn-primary` / `.btn-secondary`** — blue primary, outlined
  secondary, `--radius-sm` (8), subtle hover, disabled state.
- **`.data-table`** — consistent header weight, row padding `--sp-3`, hairline row
  separators, hover row tint.
- **Invisible-text fix:** `commission_ledger.html:42` `.agent-tab.active` →
  `color:var(--on-gold)` (white on blue) instead of `var(--ink)`.

## 5. The login rebuild

Rebuild `app/templates/login.html` from the LOCKED spec
`docs/superpowers/specs/login-redesign-LOCKED-2026-06-10.md` (Tim approved via
visual prototyping; assets in `docs/login-assets/`, final render =
`docs/login-assets/login-prototype-FINAL.html`). Summary of the locked design:
- One **frosted-glass card** centered on a **full-bleed animated waving blue→green
  gradient** (`linear-gradient(135deg,#1B5380,#266EA5 28%,#3E8FA0 52%,#65BB84 78%,#79C795)`,
  `background-size:260% 260%`, `wave` 14s; one faint radial sheen; NO soft-light
  blobs — they washed the blue out).
- In the card: big bold title **FOUNDERS** (all caps, `letter-spacing:0.10em`,
  white) over **Agent Portal** (white), both with the navy GLOW text-shadow
  ("option C": `0 1px 2px rgba(0,28,52,.7), 0 3px 10px rgba(0,30,60,.6), 0 6px 30px rgba(0,30,60,.55)`)
  — white fill + navy glow, NOT navy fill (muddy on glass). Then the animated
  logo; then "Welcome back" + Google sign-in + domain note.
- **Animation = the soul:** logo assembles part-by-part (hand scale-fade — NO
  stroke-draw, it cut the hand; bowl+rim rise; pestle springs in) then the
  **PESTLE GRINDS FOREVER** (subtle perpetual compounding — the Cannon Pharmacy
  origin, Brian's first business). ~1.6s intro. **`prefers-reduced-motion` →
  fully static, logo shown.**
- Card spec: width ~392px, `rgba(255,255,255,.15)`, `backdrop-filter:blur(24px)
  saturate(140%)`, border `rgba(255,255,255,.45)`, `--radius` (use 14? login uses
  22px — login is standalone/showpiece, keep its 22px card radius; the system
  radius governs the in-app pages, not this hero card). Logo lift via
  `drop-shadow`, NOT a frosted disc (disc covered the title).
- **Extract the logo:** save the animatable icon SVG from
  `docs/login-assets/founders_icon.svg` to **`app/static/img/founders-mark.svg`**
  (4 separable paths: p-hand/p-bowl/p-rim/p-pestle). Reuse portal-wide (sidebar,
  recap) — replaces the 2560px PNG.
- `login.html` stays **standalone** (own `<style>`, doesn't extend base.html) but
  uses the Phase 1 tokens where they apply (fonts, blue/green).

## 6. Testing / verification (browser, not unit tests — this is visual/CSS)

No Python changes → the existing **198-test suite must stay green** (it will).
Verification is rendered-output inspection:
- **After token changes:** load base/sidebar/dashboard in **light AND dark** —
  nothing clipped, borders visible both modes, no invisible text, radii consistent.
- **Login:** animation plays + **pestle keeps compounding**; title aligns
  (FOUNDERS width = Agent Portal); reduced-motion → clean static; Google sign-in
  flow still works.
- **Non-regression spot-check:** open 2–3 untouched content pages (customers, a
  commission page) and confirm the token value shifts (16→14 radius, 9→12px floor)
  **improved them without breaking layout** — the "didn't cascade-break" check.
- **HIGHEST-RISK change = the `.card` redefinition** (153 usages inherit it at
  once). After changing `.card`, specifically inspect the densest card-heavy pages
  (customers list, a commission ledger, dashboard) in both themes BEFORE
  proceeding — if the new padding/radius crowds or breaks any, adjust the `.card`
  rule (not the pages) until they all sit right. This is the one change to verify
  most carefully; everything else is lower-blast-radius.
- Verify in BOTH themes for every visual change (screenshot/inspect).

## 7. Out of scope (Phase 2+ / later)
- Refactoring the 22 content pages to fully adopt utility classes (one page per
  spec, top-down).
- The IA/module-overlap rework (commission audit vs ledger vs reconciliation vs
  recap) — flagged for the commission-cluster page phase.
- Mobile responsiveness (U2) and login speed (U3).
- `labels.html` stays excluded (print utility, hardcoded light colors).

## 8. Summary of changes
- **`app/templates/base.html`:** add type/radius/spacing tokens to `:root` (+ dark
  block); refine `.card`/`.btn*`/`.badge`/`.data-table` + hover/focus rules; apply
  to sidebar/topbar/base layout. Keep token names.
- **`app/templates/login.html`:** full rebuild to the locked login design.
- **`app/static/img/founders-mark.svg`:** new reusable logo asset (extracted).
- **`app/templates/commission_ledger.html:42`:** invisible-text fix.
- **No Python, no migration.** 198 tests stay green.

Likely TWO implementation plans (writing-plans): (1) the system+chrome token
refactor, (2) the standalone login rebuild + logo asset. They're independent.
Phase 2+ pages follow in later specs. See [[session-handoff-2026-06-10-m2]],
[[roadmap-2026-06-09]], and `login-redesign-LOCKED-2026-06-10.md`.
