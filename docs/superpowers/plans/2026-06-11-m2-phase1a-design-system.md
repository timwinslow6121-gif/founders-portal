# M2 Phase 1A — Design System + Chrome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the Founders design-system tokens (type/radius/spacing scales) in `base.html` and refine the shared component classes (`.card`/`.btn`/`.badge`/`.data-table` + hover/focus) so the whole portal inherits a consistent, readable, "soft & tactile" finish — fixing the tiny-text, mismatched-radii, and invisible-text problems at their source.

**Architecture:** All changes are CSS-only inside `app/templates/base.html` (plus a one-line fix in `commission_ledger.html`). New tokens go in the BASE `:root` only (type/radius/spacing are theme-independent, so they inherit into light/dark/data-theme blocks automatically — no need to duplicate them across the 4 theme blocks). Component classes already exist; we refine their values to use the new tokens. No Python, no migration, no template-structure changes — the 22 content pages inherit the improvements untouched.

**Tech Stack:** Vanilla CSS in Jinja2 `base.html`. Verification = browser rendering in light + dark (not unit tests). The existing 198-test suite must stay green (no Python touched).

**Spec:** `docs/superpowers/specs/2026-06-11-m2-phase1-design-system-design.md`

---

## File Structure

- **Modify:** `app/templates/base.html` — (a) add type/radius/spacing tokens to the base `:root` (~line 80, near the existing `--radius`); (b) change `--radius:16px→14px`, `--radius-sm:10px→8px`, add `--radius-pill`; (c) set `body` font-size/line-height to the new tokens; (d) refine `.card` (418), `.card-title` (438), `.badge` (450), `.btn-primary` (470), `.btn-secondary` (496), `.data-table` (541) to use new tokens + fix sizes; (e) add a global focus-ring rule.
- **Modify:** `app/templates/commission_ledger.html:42` — invisible-text fix.

**Verification note for ALL tasks:** after each visual change, the implementer should describe what changed and (where possible) confirm the app still renders by loading it. Since this is a headless environment, the controller will do the actual browser light/dark verification at review time. Each task stays small so a regression is easy to localize.

---

## Task 1: Add the design-system tokens to base.html `:root`

**Files:**
- Modify: `app/templates/base.html` (base `:root`, the `--radius` area ~line 80-82)

- [ ] **Step 1: Locate the radius tokens.** In `app/templates/base.html`, the base `:root` ends with:
```css
      /* Radius — softer/airier */
      --radius:    16px;
      --radius-sm: 10px;
    }
```

- [ ] **Step 2: Replace that block** with the new radius values + the full type and spacing scales (these are theme-independent, so base `:root` only):
```css
      /* Radius scale (M2 Phase 1) */
      --radius:      14px;   /* cards, panels (was 16) */
      --radius-sm:   8px;    /* buttons, inputs, controls (was 10) */
      --radius-pill: 999px;  /* badges, tabs, chips */

      /* Type scale (M2 Phase 1) — 12px hard floor, 15px body */
      --fs-display: 30px;  /* big numbers, hero */
      --fs-h1:      24px;
      --fs-h2:      19px;
      --fs-h3:      17px;
      --fs-body:    15px;  /* default body */
      --fs-sm:      13px;  /* secondary / labels */
      --fs-xs:      12px;  /* smallest meta — FLOOR */
      --lh:         1.5;

      /* Spacing scale (M2 Phase 1) — 4px grid */
      --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
      --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;
    }
```

- [ ] **Step 3: Verify the CSS is well-formed** (no stray brace). Run:
```bash
python3 -c "
css=open('app/templates/base.html').read()
o=css.count('{'); c=css.count('}')
print('braces balanced:', o==c, '(',o,'vs',c,')')
print('has --fs-body:', '--fs-body' in css, '| --radius: 14px:', '--radius:      14px' in css or '--radius:    14px' in css)
"
```
Expected: braces balanced True; tokens present True.

- [ ] **Step 4: Confirm app still boots (template parses).** Run:
```bash
DATABASE_URL="sqlite:///:memory:" RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app=create_app()
with app.app_context():
    from flask import render_template_string
    # render base via a child to ensure Jinja parses it
    print('base.html parses OK')
"
```
Expected: prints `base.html parses OK` (no Jinja/syntax error).

- [ ] **Step 5: Commit**
```bash
git add app/templates/base.html
git commit -m "feat(m2): add type/radius/spacing design tokens to base.html

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Set the base body type from the new tokens

**Files:**
- Modify: `app/templates/base.html` (the `body` rule)

- [ ] **Step 1: Find the `body` rule** in base.html. Run to locate it:
```bash
grep -n "^    body\|^    body {" app/templates/base.html | head
```

- [ ] **Step 2: Read the current body rule** (the lines from that match to its closing `}`), then ensure it includes these declarations (add or update — do NOT remove existing background/color/font-family lines, just set the size/line-height to tokens):
```css
      font-size: var(--fs-body);
      line-height: var(--lh);
```
If the body rule already sets `font-size`/`line-height` to a hardcoded value (e.g. `14px`), replace those values with the tokens above. Keep `font-family: var(--font-sans)` and all other existing declarations.

- [ ] **Step 3: Verify.** Run:
```bash
python3 -c "
css=open('app/templates/base.html').read()
print('body uses --fs-body:', 'var(--fs-body)' in css)
print('braces balanced:', css.count('{')==css.count('}'))
"
```
Expected: both True.

- [ ] **Step 4: Commit**
```bash
git add app/templates/base.html
git commit -m "feat(m2): base body text = 15px via --fs-body token

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Refine `.card` + `.card-title` + `.card-body`

**Files:**
- Modify: `app/templates/base.html` (lines ~418-445)

- [ ] **Step 1: Replace the `.card`, `.card:hover`, `.card-title`, `.card-body` rules.** Current `.card` (418) uses `--surface-low` and a `-2px` hover lift; `.card-title` (438) is 14px; `.card-body` (445) has hardcoded padding. Replace these four rules with:
```css
    .card {
      background: var(--surface);
      overflow: hidden;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      box-shadow: var(--shadow-sm);
      transition: transform 0.2s cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 0.2s cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    .card:hover {
      transform: translateY(-1px);
      box-shadow: var(--shadow-float);
    }
```
(Leave `.card-header` at line 429 unchanged.) Then update `.card-title`:
```css
    .card-title {
      font-family: var(--font-serif);
      font-size: var(--fs-h3);
      font-weight: 700;
      color: var(--ivory-bright);
      letter-spacing: 0.01em;
    }
```
And `.card-body`:
```css
    .card-body { padding: var(--sp-5) var(--sp-6); }
```

- [ ] **Step 2: Verify braces + tokens.** Run:
```bash
python3 -c "
css=open('app/templates/base.html').read()
print('braces balanced:', css.count('{')==css.count('}'))
print('.card uses --surface + --shadow-sm:', 'background: var(--surface);' in css)
"
```
Expected: True / True.

- [ ] **Step 3: Commit**
```bash
git add app/templates/base.html
git commit -m "feat(m2): refine .card — white surface, soft shadow, 1px hover lift, h3 title

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

**⚠ Controller verification after this task:** this is the HIGHEST-RISK change (153 `.card` usages inherit it). At review, load customers list + a commission ledger + dashboard in BOTH light and dark; confirm cards aren't crowded/broken. If any are, adjust the `.card` rule (not the pages).

---

## Task 4: Fix tiny text in `.badge` and `.btn-*`

**Files:**
- Modify: `app/templates/base.html` (lines ~450-521)

- [ ] **Step 1: Refine `.badge`** (currently 9px — below the 12px floor). Replace the `.badge` rule (450) with:
```css
    .badge {
      font-size: var(--fs-xs);
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: var(--sp-1) var(--sp-2);
      border-radius: var(--radius-pill);
      display: inline-block;
    }
```
(Leave the `.badge-red/.badge-blue/...` color variants below it unchanged.)

- [ ] **Step 2: Refine `.btn-primary`** (currently 10px). In the `.btn-primary` rule (470), change `font-size: 10px;` to `font-size: var(--fs-sm);`, `padding: 10px 20px;` to `padding: var(--sp-3) var(--sp-5);`, `border-radius` (add if missing) `var(--radius-sm);`, and reduce `letter-spacing: 0.15em;` to `letter-spacing: 0.04em;` and REMOVE `text-transform: uppercase;` (15px+ uppercase tracking reads as shouty; sentence case is cleaner at the new size). Keep everything else.

- [ ] **Step 3: Refine `.btn-secondary`** (470's sibling at 496) identically: `font-size: var(--fs-sm);`, `padding: var(--sp-3) var(--sp-5);`, `border-radius: var(--radius-sm);`, `letter-spacing: 0.04em;`, remove `text-transform: uppercase;`. Keep the rest.

- [ ] **Step 4: Verify.** Run:
```bash
python3 -c "
css=open('app/templates/base.html').read()
print('no 9px/10px in badge/btn area:', css.count('font-size: 9px')==0 and css.count('font-size: 10px')==0)
print('braces balanced:', css.count('{')==css.count('}'))
"
```
Expected: True / True. (If other unrelated 9px/10px exist elsewhere this may print False — in that case manually confirm only the badge/btn ones changed.)

- [ ] **Step 5: Commit**
```bash
git add app/templates/base.html
git commit -m "feat(m2): readable badges/buttons (12-13px, pill/8px radius, sentence case)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Refine `.data-table` + add a global focus ring

**Files:**
- Modify: `app/templates/base.html` (`.data-table` ~541, + new focus rule)

- [ ] **Step 1: Bump `.data-table` body text** from 13px to the body size for readability. In the `.data-table` rule (541), change `font-size: 13px;` to `font-size: var(--fs-sm);` (keep 13px-equivalent for dense tables — `--fs-sm` IS 13px, so this just tokenizes it; do NOT bump tables to 15px, they'd get too heavy). Leave the rest of `.data-table` and its `th`/`td` rules unchanged.

- [ ] **Step 2: Add a global focus-ring rule** for keyboard accessibility. Add this immediately AFTER the `.btn-secondary:active` rule (~line 521):
```css
    /* Accessibility: visible focus ring on interactive elements (M2 Phase 1) */
    a:focus-visible, button:focus-visible, input:focus-visible,
    select:focus-visible, textarea:focus-visible, [tabindex]:focus-visible {
      outline: 2px solid var(--gold);
      outline-offset: 2px;
      border-radius: var(--radius-sm);
    }
```

- [ ] **Step 3: Verify.** Run:
```bash
python3 -c "
css=open('app/templates/base.html').read()
print('focus-visible rule present:', ':focus-visible' in css)
print('braces balanced:', css.count('{')==css.count('}'))
"
```
Expected: True / True.

- [ ] **Step 4: Commit**
```bash
git add app/templates/base.html
git commit -m "feat(m2): tokenize data-table size + add global focus ring (a11y)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Fix the invisible-text bug

**Files:**
- Modify: `app/templates/commission_ledger.html:42`

- [ ] **Step 1: Fix the active-tab text color.** Line 42 currently is:
```css
.agent-tab.active { background: var(--gold); color: var(--ink); border-color: var(--gold); font-weight: 700; }
```
`var(--ink)` is the page-background color (near-invisible on the blue `--gold` background). Change `color: var(--ink)` to `color: var(--on-gold)` (white-on-blue, the correct readable token):
```css
.agent-tab.active { background: var(--gold); color: var(--on-gold); border-color: var(--gold); font-weight: 700; }
```

- [ ] **Step 2: Confirm no other `color:var(--ink)` text bugs.** Run:
```bash
grep -rn "color:\s*var(--ink)" app/templates/*.html
```
Expected: no results (the ledger one is fixed; if any others appear, they are the same bug — fix each to the appropriate readable token, usually `var(--ivory)` for text on a surface or `var(--on-gold)` for text on the blue accent).

- [ ] **Step 3: Commit**
```bash
git add app/templates/commission_ledger.html
git commit -m "fix(m2): invisible active-tab text (var(--ink) -> var(--on-gold))

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Full regression + render verification

**Files:** none (verification)

- [ ] **Step 1: Full test suite** (no Python changed → must stay green):
```bash
python3 -m pytest -q
```
Expected: 198 passed (unchanged).

- [ ] **Step 2: Confirm base.html still parses + app boots:**
```bash
DATABASE_URL="sqlite:///:memory:" RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app=create_app(); c=app.test_client()
r=c.get('/auth/login'); print('login status', r.status_code)
print('base tokens present:', all(t in open('app/templates/base.html').read() for t in ['--fs-body','--radius-pill','--sp-6']))
"
```
Expected: `login status 200`; tokens present True.

- [ ] **Step 3: Controller browser verification (manual, at review).** Load in BOTH light + dark, confirm: (a) body text noticeably more readable (15px), (b) badges/buttons no longer tiny, (c) card radii consistent (14px) and not crowded, (d) the commission_ledger active tab text is now readable, (e) no clipped text / broken layout on dashboard, customers list, a commission page. Adjust tokens (not pages) if anything's off.

- [ ] **Step 4: Commit (only if a fixup was needed)** — otherwise skip.

---

## Task 8: Docs

**Files:**
- Modify: spec Status; CLAUDE.md (UX section + START HERE); the design-system memory

- [ ] **Step 1: Mark spec Status** → `✅ Implemented (Phase 1A — system+chrome; local) — login (1B) next`.

- [ ] **Step 2: Update CLAUDE.md** — in the "UX Design System — FOUNDERS RE-THEME" section, note the M2 Phase 1 token additions (type scale 15px/12px-floor, radius 14/8/pill, spacing 4px grid, refined components). Update START HERE: Phase 1A system done → **login rebuild (Phase 1B) next**, then Phase 2+ pages.

- [ ] **Step 3: Commit**
```bash
git add docs/superpowers/specs/2026-06-11-m2-phase1-design-system-design.md CLAUDE.md
git commit -m "docs(m2): Phase 1A design-system implemented; next=login rebuild

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (spec §3–§6 → tasks):
- §3 type scale → Task 1 (tokens) + Task 2 (body) + Tasks 3-5 (applied to components). ✓
- §3 radius scale (14/8/pill) → Task 1. ✓
- §3 spacing scale → Task 1 (tokens) + Tasks 3-4 (applied). ✓
- §3 colors unchanged, names kept → confirmed (no color/name changes in any task). ✓
- §4 component rules: `.card` → Task 3; `.badge` → Task 4; `.btn*` → Task 4; `.data-table` → Task 5; hover (no-layout-shift translateY) → Task 3; focus ring → Task 5; invisible-text fix → Task 6. ✓
- §6 testing (198 green, browser light+dark, .card highest-risk check) → Task 3 controller note + Task 7. ✓
- §5 login → NOT here (separate Plan 1B, by design). ✓

**Placeholder scan:** no TBD/TODO. Each CSS step shows the exact replacement code. The few "locate the rule" steps give a grep command + the known line number; the implementer reads the real surrounding lines before editing (correct for CSS edits where exact current text must match). Not vague — precise instructions.

**Type/name consistency:** token names (`--fs-body/-sm/-xs/-display/-h1/-h2/-h3`, `--lh`, `--radius/-sm/-pill`, `--sp-1..8`) defined once in Task 1, referenced identically in Tasks 2-5. `--on-gold` (Task 6) and `--gold`/`--surface`/`--shadow-*` are existing tokens, used correctly. No new Python symbols.

**Note on test design:** this plan has NO unit tests (it's pure CSS/visual) — verification is brace-balance + parse checks (automatable) plus controller browser inspection in both themes (the real check). This is the correct verification model for a token/CSS refactor; unit tests can't see "is the radius consistent" or "is the text readable." Stated explicitly so the executor doesn't expect TDD red/green here.
