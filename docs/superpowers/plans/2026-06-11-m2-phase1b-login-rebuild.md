# M2 Phase 1B — Login Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `app/templates/login.html` with the LOCKED login redesign — a frosted-glass card on an animated waving blue→green gradient, big "FOUNDERS / Agent Portal" title, and the Founders logo animating with a perpetually-compounding pestle — plus extract the logo as a reusable SVG asset. (Also fixes the U3 "slow login" by dropping the dead Noto Serif/Inter font link.)

**Architecture:** `login.html` is standalone (its own `<style>`, does NOT extend base.html) — keep it that way, but use the Founders fonts/colors. The animated logo is inline SVG (4 separable paths) so its parts animate via CSS. A reusable copy of the icon is saved to `app/static/img/founders-mark.svg`. The Google sign-in flow and the `error` flash param are preserved exactly. `prefers-reduced-motion` shows a clean static version.

**Tech Stack:** Vanilla HTML/CSS/inline-SVG in a standalone Jinja2 template. Verification = browser (animation plays, pestle compounds, title aligns, reduced-motion static, Google login works). No Python beyond confirming the route. 198-test suite stays green.

**Spec:** `docs/superpowers/specs/2026-06-11-m2-phase1-design-system-design.md` §5
**Locked design:** `docs/superpowers/specs/login-redesign-LOCKED-2026-06-10.md`
**Reference render:** `docs/login-assets/login-prototype-FINAL.html` (the approved prototype — the new login.html should match this)
**Logo source:** `docs/login-assets/founders_icon.svg` + `docs/login-assets/icon_parts.txt` (the 4 animatable paths, classes p-hand/p-bowl/p-rim/p-pestle)

---

## File Structure

- **Create:** `app/static/img/founders-mark.svg` — clean reusable icon (from `docs/login-assets/founders_icon.svg`). Portal-wide asset (login now; sidebar/recap later).
- **Replace:** `app/templates/login.html` — full rebuild to the locked design. Standalone. Keeps the `{{ error }}` display + the Google sign-in link/form exactly as the current one wires it.
- **No change:** `app/auth.py` (route already renders `login.html` with optional `error=`). Confirm only.

**Key facts the implementer must preserve from the CURRENT login.html:**
- It's rendered by `app/auth.py` `login()` (no args) and `callback()` (with `error='Access restricted to @foundersinsuranceagency.com accounts.'` on non-domain). So the new template MUST render `{{ error }}` if present (e.g. a red notice in the card).
- The Google sign-in action: check the current login.html for how it links to `auth.google_login` (likely an `<a href="{{ url_for('auth.google_login') }}">`). REUSE that exact link/markup so OAuth keeps working — do not invent a new endpoint.

---

## Task 1: Extract the reusable logo SVG asset

**Files:**
- Create: `app/static/img/founders-mark.svg`

- [ ] **Step 1: Create the static dir + copy the clean icon.** Run:
```bash
mkdir -p app/static/img
cp docs/login-assets/founders_icon.svg app/static/img/founders-mark.svg
ls -l app/static/img/founders-mark.svg
```
Expected: file exists (~8-11KB).

- [ ] **Step 2: Verify it's a valid standalone SVG** (renders to PNG via Inkscape, which is installed):
```bash
inkscape app/static/img/founders-mark.svg --export-type=png --export-filename=/tmp/mark_check.png --export-width=120 2>/dev/null && ls -l /tmp/mark_check.png && echo "renders OK"
```
Expected: PNG produced, "renders OK". (This is the mortar+pestle-in-hand mark in blue/green.)

- [ ] **Step 3: Confirm Flask serves it.** Run:
```bash
DATABASE_URL="sqlite:///:memory:" RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app=create_app(); c=app.test_client()
r=c.get('/static/img/founders-mark.svg')
print('static svg status', r.status_code, '| content-type', r.headers.get('Content-Type'))
"
```
Expected: status 200, content-type image/svg+xml (Flask's default static route serves it).

- [ ] **Step 4: Commit**
```bash
git add app/static/img/founders-mark.svg
git commit -m "feat(m2): add reusable founders-mark.svg logo asset

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Build the new login.html (the full rebuild)

**Files:**
- Replace: `app/templates/login.html`
- Read first: `docs/login-assets/login-prototype-FINAL.html` (the approved design — match it), `docs/login-assets/icon_parts.txt` (the 4 animated paths), and the CURRENT `app/templates/login.html` (to copy the exact `{{ error }}` + `auth.google_login` markup).

- [ ] **Step 1: Read the three reference files.** Run:
```bash
sed -n '1,40p' app/templates/login.html        # current: grab the error display + google link markup
grep -n "error\|google_login\|url_for" app/templates/login.html
cat docs/login-assets/icon_parts.txt           # the 4 inline-SVG paths (p-hand/p-bowl/p-rim/p-pestle)
```
Note the EXACT Jinja for the error message and the Google sign-in link — you will reuse them verbatim.

- [ ] **Step 2: Write the new `app/templates/login.html`.** Base it on `docs/login-assets/login-prototype-FINAL.html` (the approved v5 render) with these REQUIRED productionizations:
  1. **Fonts:** load ONLY `Plus Jakarta Sans` + `Merriweather` (drop Noto Serif/Inter — that dead link is the U3 slow-login cause). Use the same Google Fonts link as the prototype.
  2. **The animated logo:** use the inline SVG from `icon_parts.txt` (the `<svg viewBox="0 0 97 97"><g transform="matrix(...)"><g transform="scale(0.1)"> + the 4 <path class="p-..."> </g></g></svg>` structure exactly as in the prototype). Inline (not the static file) so the CSS part-animations work. (The static `founders-mark.svg` is for OTHER pages; login needs the inline animatable version.)
  3. **Title:** `FOUNDERS` (all caps) `letter-spacing: 0.10em` over `Agent Portal`, both white, with the navy-glow text-shadow (option C): `text-shadow:0 1px 2px rgba(0,28,52,.7),0 3px 10px rgba(0,30,60,.6),0 6px 30px rgba(0,30,60,.55);`.
  4. **Animation:** card fade-in → title → hand scale-fade (NO stroke-draw) → bowl+rim rise → pestle springs in → pestle GRINDS forever (`grind` 2.8s infinite, the compounding motion). ~1.6s intro. Copy the exact keyframes from the prototype.
  5. **Gradient:** `linear-gradient(135deg,#1B5380,#266EA5 28%,#3E8FA0 52%,#65BB84 78%,#79C795)`, `background-size:260% 260%`, `wave` 14s + faint radial sheen. NO soft-light blobs.
  6. **Error display:** if `error` is passed, show it in the card (e.g. a red `.login-error` notice above or below the button). Use the SAME `{% if error %}...{{ error }}...{% endif %}` logic the current login.html uses.
  7. **Google button:** the "Sign in with Google" button must link/submit to the SAME endpoint the current login uses (`auth.google_login` via `url_for` — copy it). Keep the real Google "G" svg from the prototype.
  8. **Domain note:** "Restricted to @foundersinsuranceagency.com accounts."
  9. **`prefers-reduced-motion`:** the `@media (prefers-reduced-motion: reduce)` block from the prototype (all animations off, logo fully shown).
  10. **Remove** the prototype's `.page`/`.sub`/`.pick`/`.note`/`.replay` scaffolding and the `<h1 class="page">`/explainer text — those were prototype chrome, not part of the real login. The real page = just the centered glass card on the gradient.

- [ ] **Step 3: Verify the template parses + renders.** Run:
```bash
DATABASE_URL="sqlite:///:memory:" RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app=create_app(); c=app.test_client()
r=c.get('/auth/login')
html=r.get_data(as_text=True)
print('status', r.status_code)
print('has title FOUNDERS:', 'FOUNDERS' in html)
print('has pestle class:', 'p-pestle' in html)
print('has grind keyframe:', 'grind' in html)
print('google login link:', 'auth.google_login' in html or 'google' in html.lower())
print('reduced-motion block:', 'prefers-reduced-motion' in html)
print('NO dead Noto/Inter link:', 'Noto+Serif' not in html and 'family=Inter' not in html)
"
```
Expected: status 200; all True (and the last line True = dead fonts removed).

- [ ] **Step 4: Verify the error path still renders.** Run:
```bash
DATABASE_URL="sqlite:///:memory:" RATELIMIT_ENABLED=0 python3 -c "
from app import create_app
app=create_app()
with app.test_request_context():
    from flask import render_template
    html=render_template('login.html', error='TEST ERROR MESSAGE')
    print('error shown:', 'TEST ERROR MESSAGE' in html)
"
```
Expected: `error shown: True` (the non-domain message will display).

- [ ] **Step 5: Commit**
```bash
git add app/templates/login.html
git commit -m "feat(m2): rebuild login — frosted glass + waving gradient + compounding-pestle logo

Drops the dead Noto Serif/Inter font link (fixes U3 slow login). Preserves
the error flash + Google sign-in flow. Reduced-motion fallback included.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Full regression + render verification

**Files:** none (verification)

- [ ] **Step 1: Full suite** (no Python changed):
```bash
python3 -m pytest -q
```
Expected: 198 passed.

- [ ] **Step 2: Controller browser verification (manual, at review).** Load `/auth/login` in a real browser:
  - The intro animation plays (~1.6s): card in → title → logo assembles → pestle drops.
  - **The pestle keeps gently compounding** after the intro (the signature).
  - Title: FOUNDERS spans ~the same width as "Agent Portal"; both white with the navy glow.
  - The gradient slowly waves; no all-green washout; logo lifted/readable.
  - Toggle OS reduced-motion → page is clean + static, logo fully shown, no motion.
  - Click "Sign in with Google" → it initiates the real OAuth flow (goes to Google).
  - Trigger the error path (attempt a non-Founders Google login) → the restriction message shows in the card.
  - Check it looks right at a narrow width (the card should stay centered/usable — full mobile is U2 later, but it shouldn't be broken).

- [ ] **Step 3: Commit (only if a fixup was needed)** — otherwise skip.

---

## Task 4: Docs

**Files:**
- Modify: login-redesign-LOCKED spec Status; the m2-phase1 spec Status; CLAUDE.md; session-handoff memory

- [ ] **Step 1:** In `docs/superpowers/specs/login-redesign-LOCKED-2026-06-10.md`, add a top note: `STATUS: ✅ BUILT (local) 2026-06-11 — app/templates/login.html rebuilt to this design.`

- [ ] **Step 2:** In `docs/superpowers/specs/2026-06-11-m2-phase1-design-system-design.md`, Status → `✅ Implemented (Phase 1A + 1B, local) — pending VPS deploy + browser verify`.

- [ ] **Step 3:** Update CLAUDE.md START HERE + Build Status: M2 Phase 1 (design system + login) built local; **next = deploy + verify in browser (light+dark), then Phase 2+ pages (dashboard first)**. Note the new `app/static/img/founders-mark.svg` asset and that login no longer loads dead fonts.

- [ ] **Step 4: Commit**
```bash
git add docs/superpowers/specs/login-redesign-LOCKED-2026-06-10.md docs/superpowers/specs/2026-06-11-m2-phase1-design-system-design.md CLAUDE.md
git commit -m "docs(m2): login rebuilt; Phase 1 complete (local); next=deploy+verify then pages

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage** (spec §5 / login-LOCKED → tasks):
- Logo SVG asset extracted → Task 1. ✓
- Frosted-glass card + waving gradient (no blobs) → Task 2 step 2.5. ✓
- FOUNDERS/Agent Portal title, 0.10em, navy-glow C → Task 2 step 2.3. ✓
- Part-by-part animation + compounding pestle, no stroke-draw → Task 2 step 2.4. ✓
- reduced-motion static → Task 2 step 2.9 + verify 3.2. ✓
- error flash preserved → Task 2 step 2.6 + verify Task 2 step 4. ✓
- Google sign-in preserved → Task 2 step 2.7 + verify 3.2. ✓
- standalone template, Founders fonts, drop dead fonts (U3 win) → Task 2 steps 2.1 + verify "NO dead Noto/Inter". ✓
- 198 tests green → Task 3. ✓

**Placeholder scan:** The big "write the template" step (Task 2 Step 2) is a 10-point spec rather than a single pasted file — deliberately, because the source of truth is the approved prototype `docs/login-assets/login-prototype-FINAL.html` which the implementer copies/adapts (pasting the full 200-line file here would duplicate it and risk drift). Each of the 10 points is concrete (exact values, exact keyframes-source, exact things to remove). This is the right granularity for "adapt this existing approved artifact into production." Not vague.

**Type/name consistency:** the SVG path classes (p-hand/p-bowl/p-rim/p-pestle), the title values (0.10em, the C glow shadow string), the gradient string, and the endpoint name (`auth.google_login`) match the locked spec and the prototype. The static asset path (`app/static/img/founders-mark.svg`) is consistent between Task 1 and the file-structure note.

**Verification model:** CSS/visual feature → no unit tests; verification is parse/render checks (automatable: status 200, key strings present, error path renders, dead fonts gone) + controller browser inspection (animation, reduced-motion, OAuth). Correct for this work. The error-path and dead-font checks ARE automatable and included so regressions are caught without a browser.
