# Portal Re-Theme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-skin the whole portal to the Founders look (blue/green, Plus Jakarta Sans + Merriweather, rounded/soft) in BOTH light and dark mode, with a device-default + manual sidebar toggle that persists per-device — by swapping `base.html`'s CSS-variable values (26 pages inherit) plus a light per-page polish pass.

**Architecture:** The portal is var-driven: `base.html :root` holds light tokens, `@media (prefers-color-scheme: dark) :root` holds dark tokens, and all pages use `var(--…)`. The re-theme swaps those token VALUES to the Founders palettes (semantic roles preserved: `--ink`=background, `--ivory`=readable text), adds `:root[data-theme="light|dark"]` override blocks + a no-flash pre-paint script so a manual toggle wins over the OS setting, swaps the fonts, and adds a sidebar-footer toggle. Verification is by rendered screenshots in both modes (it's CSS — no unit tests), plus the existing pytest suite to confirm no template breaks.

**Tech Stack:** Jinja2 templates, CSS custom properties, vanilla JS (localStorage + `data-theme`), headless Chrome for visual verification.

---

## Critical constraints (read first)

- **Semantic token roles MUST be preserved** (per CLAUDE.md "Color Token Reference"): `--ink` = BACKGROUND (light grey in light, near-black in dark), `--ivory` = readable TEXT, `--slate` = muted text, `--gold` = accent, `--surface` = card. Templates rely on these roles. Swap VALUES, never repurpose a token. Any text `color:` uses `--ivory`/`--slate`, never `--ink`.
- **`labels.html` is EXCLUDED** — print utility with intentionally hardcoded colors. Do not touch it.
- **No models / migrations / routes** — pure presentation. The existing pytest suite must stay green (templates render in route tests).
- **Verify in BOTH modes by screenshot** — the recap CSS nesting bug + the gradient washout were only caught by real rendering, not tests. Same discipline here.

## Current state (verified)

`base.html` already has the exact structure to re-skin:
- `:root` (lines ~19-66): light tokens incl. `--ink --surface --surface-low/mid/high/top --gold --gold-dim --gold-muted --ivory --ivory-bright --slate --on-gold --outline --outline-var --border --status-* --font-serif --font-sans --sidebar-w --topbar-h --shadow-float --radius`.
- `@media (prefers-color-scheme: dark) :root` (lines ~68-100): dark values for the same tokens.
- Two font links (lines 9-10): Noto Serif+Inter (old) AND Merriweather+Plus Jakarta Sans (added for recap).
- Sidebar footer (lines ~767-773): avatar + display name + Sign Out link — toggle goes here.

## File structure

- **Modify** `app/templates/base.html` — ALL the theme work: token-value swap (both blocks), `[data-theme]` override blocks, pre-paint script, fonts dedupe, default font-family swap, sidebar toggle button + JS.
- **Modify** `app/templates/commission/recap.html` — point its scoped `--rc-*` tokens at the new globals so it follows light/dark.
- **Modify** `app/templates/login.html` — outside the sidebar; verify/fix palette in both modes.
- **Targeted polish** across content templates only where flat (most inherit automatically).
- **Untouched:** `labels.html`.

---

### Task 1: Swap light-mode tokens to the Founders palette

**Files:** Modify `app/templates/base.html` (`:root` block, ~lines 19-66)

- [ ] **Step 1: Replace the light `:root` token VALUES**

In `base.html`, replace the `:root { … }` block's values with the Founders light palette (keep token NAMES, add `--green*`):

```css
    :root {
      /* Surfaces (Founders light) */
      --ink:          #F7FAFC;   /* page background */
      --surface:      #FFFFFF;   /* card */
      --surface-low:  #EEF3F8;
      --surface-mid:  #E4ECF3;
      --surface-high: #D9E4EF;
      --surface-top:  #CBD5E0;

      /* Accent — Founders blue (replaces gold; name kept for compat) */
      --gold:         #266EA5;
      --gold-dim:     #1F5A85;
      --gold-muted:   #2B6CB0;

      /* Green accent (positive / success) */
      --green:        #65BB84;
      --green-dim:    #13612E;

      /* Text */
      --ivory:        #1A202C;   /* readable body text */
      --ivory-bright: #002E4D;   /* navy — headings */
      --slate:        #718096;   /* muted */
      --on-gold:      #FFFFFF;

      /* Structural */
      --outline:      #9AA7B5;
      --outline-var:  #CBD5E0;
      --border:       rgba(26,32,44,0.10);

      /* Status */
      --status-open:       #718096;
      --status-progress:   #F7630C;
      --status-waiting:    #5C4DB1;
      --status-resolved:   #13612E;
      --status-error:      #B82105;
      --status-error-bg:   rgba(184,33,5,0.06);
      --status-error-text: #B82105;

      /* Typography — Founders */
      --font-serif: 'Merriweather', Georgia, serif;
      --font-sans:  'Plus Jakarta Sans', -apple-system, sans-serif;

      /* Layout */
      --sidebar-w:  220px;
      --topbar-h:   52px;

      /* Elevation — soft, blue-tinted */
      --shadow-float: 0px 8px 32px rgba(38,110,165,0.12);
      --shadow:       0px 6px 24px rgba(38,110,165,0.10);
      --shadow-sm:    0px 2px 8px rgba(0,0,0,0.05);

      /* Radius — softer/airier */
      --radius:    16px;
      --radius-sm: 10px;
    }
```

- [ ] **Step 2: Render the dashboard in light mode and eyeball**

Run (renders a representative page through base.html with a logged-in user — adapt the snippet to the repo's test-client login, mirroring tests/test_customer_edit.py):
```bash
python3 - <<'PY'
import os; os.environ.update(SECRET_KEY='x',TESTING='1',DATABASE_URL='sqlite:///:memory:')
from app import create_app; from app.extensions import db
a=create_app(); a.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',SERVER_NAME='localhost',LOGIN_DISABLED=True)
from app.models import Agency,User
with a.app_context():
    db.create_all()
    ag=Agency(name="F"); db.session.add(ag); db.session.flush()
    u=User(name="Tim Winslow",email="t@x.com",agency_id=ag.id,is_admin=True); db.session.add(u); db.session.flush()
    c=a.test_client()
    with c.session_transaction() as s: s["_user_id"]=str(u.id)
    open("/tmp/theme_dash.html","wb").write(c.get("/").data)
    print("rendered", os.path.getsize("/tmp/theme_dash.html"))
PY
google-chrome --headless --disable-gpu --no-sandbox --window-size=1440,900 --virtual-time-budget=3000 --screenshot=/tmp/theme_light.png --hide-scrollbars file:///tmp/theme_dash.html 2>/dev/null
```
Expected: dashboard renders in the new blue/green light palette, readable text (no light-on-light). View `/tmp/theme_light.png`. If any text is invisible, it's a `--ink` vs `--ivory` misuse in that page — note it for Task 6.

- [ ] **Step 3: Run the test suite (no template breaks)**

Run: `python3 -m pytest -q 2>&1 | tail -3`
Expected: all pass (unchanged count — CSS only).

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(theme): Founders light palette + fonts in base.html :root"
```

---

### Task 2: Swap dark-mode tokens to the Founders dark palette

**Files:** Modify `app/templates/base.html` (`@media (prefers-color-scheme: dark) :root`, ~lines 68-100)

- [ ] **Step 1: Replace the dark `:root` token VALUES**

Replace the dark block's values with the approved Founders dark palette:

```css
    @media (prefers-color-scheme: dark) {
      :root {
        --ink:          #0E1726;   /* page bg */
        --surface:      #172338;   /* card */
        --surface-low:  #1E2C44;
        --surface-mid:  #243353;
        --surface-high: #2B3D60;
        --surface-top:  #324872;

        --gold:         #4A9FD4;   /* brightened blue */
        --gold-dim:     #3E86B8;
        --gold-muted:   #2E6E9E;

        --green:        #7BD49B;
        --green-dim:    #3E8E63;

        --ivory:        #E2E8F0;
        --ivory-bright: #F5F8FB;
        --slate:        #8AA0B8;
        --on-gold:      #04243B;

        --outline:      #3C4A5E;
        --outline-var:  #24344D;
        --border:       #24344D;

        --status-open:       #8AA0B8;
        --status-progress:   #F7A35C;
        --status-waiting:    #9D8DF1;
        --status-resolved:   #7BD49B;
        --status-error:      #FFB4AB;
        --status-error-bg:   rgba(255,180,171,0.08);
        --status-error-text: #FFB4AB;

        --shadow-float: 0px 24px 48px rgba(0,0,0,0.5);
        --shadow:       0px 8px 28px rgba(0,0,0,0.45);
        --shadow-sm:    0px 2px 8px rgba(0,0,0,0.4);
      }
    }
```

- [ ] **Step 2: Render the dashboard in dark mode and eyeball**

Run (same render as Task 1 Step 2, but force dark in headless):
```bash
google-chrome --headless --disable-gpu --no-sandbox --window-size=1440,900 --virtual-time-budget=3000 --force-dark-mode --screenshot=/tmp/theme_dark.png --hide-scrollbars file:///tmp/theme_dash.html 2>/dev/null
```
(If `--force-dark-mode` doesn't drive `prefers-color-scheme`, instead inject `<meta name="color-scheme" content="dark">` is insufficient — better: temporarily test via the `[data-theme="dark"]` attribute built in Task 3, then re-verify here. For this step, the goal is to confirm the dark token values are syntactically applied; full dark verification happens after Task 3.)
Expected: navy-slate surfaces, light text, brightened blue/green accents, readable.

- [ ] **Step 3: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(theme): Founders dark palette in base.html"
```

---

### Task 3: Manual toggle override — `[data-theme]` blocks + pre-paint script

**Files:** Modify `app/templates/base.html` (add after the dark `@media` block, and a script in `<head>`)

- [ ] **Step 1: Add explicit `[data-theme]` override blocks**

In `base.html`, immediately AFTER the closing `}` of the `@media (prefers-color-scheme: dark)` block (~line 100), add blocks that let a manual `data-theme` attribute on `<html>` win over the OS setting. These duplicate the light/dark token values but key off the attribute (higher specificity + later source order than the media query):

```css
    /* Manual override: data-theme on <html> wins over the OS media query. */
    :root[data-theme="light"] {
      --ink:#F7FAFC; --surface:#FFFFFF; --surface-low:#EEF3F8; --surface-mid:#E4ECF3;
      --surface-high:#D9E4EF; --surface-top:#CBD5E0;
      --gold:#266EA5; --gold-dim:#1F5A85; --gold-muted:#2B6CB0;
      --green:#65BB84; --green-dim:#13612E;
      --ivory:#1A202C; --ivory-bright:#002E4D; --slate:#718096; --on-gold:#FFFFFF;
      --outline:#9AA7B5; --outline-var:#CBD5E0; --border:rgba(26,32,44,0.10);
      --status-open:#718096; --status-progress:#F7630C; --status-waiting:#5C4DB1;
      --status-resolved:#13612E; --status-error:#B82105;
      --status-error-bg:rgba(184,33,5,0.06); --status-error-text:#B82105;
      --shadow-float:0px 8px 32px rgba(38,110,165,0.12);
      --shadow:0px 6px 24px rgba(38,110,165,0.10); --shadow-sm:0px 2px 8px rgba(0,0,0,0.05);
    }
    :root[data-theme="dark"] {
      --ink:#0E1726; --surface:#172338; --surface-low:#1E2C44; --surface-mid:#243353;
      --surface-high:#2B3D60; --surface-top:#324872;
      --gold:#4A9FD4; --gold-dim:#3E86B8; --gold-muted:#2E6E9E;
      --green:#7BD49B; --green-dim:#3E8E63;
      --ivory:#E2E8F0; --ivory-bright:#F5F8FB; --slate:#8AA0B8; --on-gold:#04243B;
      --outline:#3C4A5E; --outline-var:#24344D; --border:#24344D;
      --status-open:#8AA0B8; --status-progress:#F7A35C; --status-waiting:#9D8DF1;
      --status-resolved:#7BD49B; --status-error:#FFB4AB;
      --status-error-bg:rgba(255,180,171,0.08); --status-error-text:#FFB4AB;
      --shadow-float:0px 24px 48px rgba(0,0,0,0.5);
      --shadow:0px 8px 28px rgba(0,0,0,0.45); --shadow-sm:0px 2px 8px rgba(0,0,0,0.4);
    }
```

(Yes, this duplicates values — it's the simplest correct cascade: OS default via media query, explicit user choice via attribute. A future refactor could share via a class, but duplication here is clear and bug-free.)

- [ ] **Step 2: Add the no-flash pre-paint script**

In `base.html` `<head>`, as the FIRST thing inside `<head>` (before the font links and `<style>`, so it runs before paint), add:

```html
  <script>
    // Apply saved theme before first paint to avoid a light→dark flash.
    (function(){
      try {
        var t = localStorage.getItem('fp-theme');
        if (t === 'light' || t === 'dark') {
          document.documentElement.setAttribute('data-theme', t);
        }
      } catch (e) {}
    })();
  </script>
```

- [ ] **Step 3: Verify the override works (render with data-theme=dark)**

Run:
```bash
python3 -c "
h=open('/tmp/theme_dash.html').read().replace('<html lang=\"en\">','<html lang=\"en\" data-theme=\"dark\">')
open('/tmp/theme_forcedark.html','w').write(h)
"
google-chrome --headless --disable-gpu --no-sandbox --window-size=1440,900 --virtual-time-budget=3000 --screenshot=/tmp/theme_dark_attr.png --hide-scrollbars file:///tmp/theme_forcedark.html 2>/dev/null
```
View `/tmp/theme_dark_attr.png`: must show the dark palette (navy bg, light text) because `data-theme="dark"` overrides. This is the definitive dark-mode check.

- [ ] **Step 4: Commit**

```bash
git add app/templates/base.html
git commit -m "feat(theme): manual data-theme override blocks + no-flash pre-paint script"
```

---

### Task 4: Sidebar theme toggle (button + JS) + fonts dedupe

**Files:** Modify `app/templates/base.html` (sidebar footer ~line 767, head font links ~lines 9-10, default body font)

- [ ] **Step 1: Dedupe the font links**

In `base.html` `<head>`, REMOVE the old Noto Serif + Inter link (line 9):
```html
  <link href="https://fonts.googleapis.com/css2?family=Noto+Serif:ital,wght@0,300;0,400;0,700;1,400&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
```
Keep ONLY the Merriweather + Plus Jakarta Sans link (line 10). (The `--font-serif`/`--font-sans` token values from Task 1 already point at the new families.)

- [ ] **Step 2: Add the toggle button to the sidebar footer**

Replace the sidebar-footer block (~lines 767-773) with one that adds the toggle:

```html
      <div class="sidebar-footer">
        <div class="sidebar-avatar">{{ current_user.initials }}</div>
        <div style="min-width:0;">
          <div class="sidebar-user-name">{{ current_user.display_name }}</div>
          <a href="/auth/logout" class="sidebar-signout">Sign Out</a>
        </div>
        <button type="button" id="themeToggle" class="theme-toggle"
                aria-label="Toggle dark mode" title="Toggle light/dark">
          <svg class="ico-sun" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>
          </svg>
          <svg class="ico-moon" width="18" height="18" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round" style="display:none">
            <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>
          </svg>
        </button>
      </div>
```

- [ ] **Step 3: Add the toggle CSS**

Near the `.sidebar-footer` rule (~line 250), add:

```css
    .sidebar-footer { display: flex; align-items: center; gap: 10px; }
    .theme-toggle {
      margin-left: auto; background: transparent; border: 1px solid var(--border);
      color: var(--ivory); border-radius: var(--radius-sm); width: 34px; height: 34px;
      display: inline-flex; align-items: center; justify-content: center; cursor: pointer;
      transition: background 0.2s, border-color 0.2s;
    }
    .theme-toggle:hover { background: var(--surface-low); border-color: var(--gold); }
    .theme-toggle:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
```

(If `.sidebar-footer` already sets display/layout, merge rather than duplicate — adjust so the toggle sits at the right via `margin-left:auto`.)

- [ ] **Step 4: Add the toggle JS + icon sync**

In `base.html`, before `</body>` (or in the existing sidebar script block), add:

```html
  <script>
    (function(){
      var btn = document.getElementById('themeToggle');
      if (!btn) return;
      var sun = btn.querySelector('.ico-sun'), moon = btn.querySelector('.ico-moon');
      function current(){
        var attr = document.documentElement.getAttribute('data-theme');
        if (attr) return attr;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      }
      function syncIcon(){
        var dark = current() === 'dark';
        sun.style.display  = dark ? 'none' : '';
        moon.style.display = dark ? '' : 'none';
      }
      syncIcon();
      btn.addEventListener('click', function(){
        var next = current() === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('fp-theme', next); } catch(e){}
        syncIcon();
      });
    })();
  </script>
```

- [ ] **Step 5: Verify toggle renders + flips (screenshot both states)**

Re-render `/` (Task 1 Step 2 snippet), screenshot default, then screenshot with `data-theme="dark"` injected (Task 3 Step 3). Confirm: toggle button visible in sidebar footer in both; sun icon shows in light, moon in dark.

- [ ] **Step 6: Run the test suite + commit**

Run: `python3 -m pytest -q 2>&1 | tail -2` (all pass).
```bash
git add app/templates/base.html
git commit -m "feat(theme): sidebar light/dark toggle (localStorage) + fonts dedupe"
```

---

### Task 5: Recap reconciliation — follow the global theme

**Files:** Modify `app/templates/commission/recap.html` (the `.recap-page { --rc-* }` block)

- [ ] **Step 1: Point the recap's scoped tokens at the globals**

In `recap.html`'s `{% block styles %}`, change the `.recap-page { --rc-… }` definitions to reference the global tokens so the recap follows light/dark automatically:

```css
  .recap-page{
    --rc-blue: var(--gold); --rc-green: var(--green); --rc-navy: var(--ivory-bright);
    --rc-ink: var(--ivory); --rc-slate: var(--slate); --rc-muted: var(--slate);
    --rc-border: var(--border); --rc-blue-tint: var(--surface-low);
    --rc-bg: var(--ink); --rc-card: var(--surface);
    --rc-success: var(--green-dim); --rc-alert: var(--status-error);
    --rc-r: var(--radius);
    --rc-shadow: var(--shadow); --rc-shadow-sm: var(--shadow-sm); --rc-shadow-lg: var(--shadow-float);
    font-family:'Plus Jakarta Sans',sans-serif; font-size:1.25rem;
    color:var(--rc-ink); line-height:1.5; max-width:1180px; margin:0 auto;
  }
```

(Carrier brand colors in the JS `CARRIER_BRAND` map stay fixed hex — they're brand identity, intentionally mode-independent. The gradient New-Members card: keep its blue→green gradient — it reads in both modes.)

- [ ] **Step 2: Verify the recap in BOTH modes**

Render the recap page (use the populated-recap render harness from the R2 work) with and without `data-theme="dark"`, screenshot both. Confirm: light mode unchanged from before; dark mode shows navy surfaces, light text, readable carrier cards, gradient card legible, drill-down readable. Fix any contrast issue (e.g. a hardcoded `#fff`/`#1a202c` left in recap CSS that should be a token).

- [ ] **Step 3: Commit**

```bash
git add app/templates/commission/recap.html
git commit -m "feat(theme): recap follows global light/dark tokens"
```

---

### Task 6: Light-polish pass + login + both-mode verification of key pages

**Files:** Modify `app/templates/login.html` and targeted content templates as needed

- [ ] **Step 1: Render the key pages in both modes**

For each of: dashboard (`/`), customers list (`/customers`), a customer profile, commission audit (`/commissions`), the recap, and `login.html` — render through the test client (logged in where required; login is public) and screenshot in light AND dark (`data-theme` injection). Build a small loop script writing `/tmp/theme_<page>_<mode>.png`.

- [ ] **Step 2: Fix issues found**

For each screenshot, check: (a) no invisible text (the `--ink` vs `--ivory` trap — any text using `var(--ink)` for color is a bug; change to `--ivory`/`--slate`), (b) cards have `border-radius: var(--radius)` + `box-shadow: var(--shadow)` + padding (add where flat), (c) buttons/badges/tables readable in both modes, (d) accent reads (blue/green). Make the minimal per-page edits. Do NOT redesign layouts.

- [ ] **Step 3: Fix `login.html` explicitly**

`login.html` is outside the sidebar (no toggle there — it inherits OS/none, which is fine pre-login). Ensure its panels use `var(--surface)`/`var(--ink)` and the Google button stays `#fff` (brand requirement). Render + screenshot light and dark; fix any hardcoded Lux colors.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q 2>&1 | tail -2`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/templates/
git commit -m "feat(theme): light-polish pass + login both-mode fixes"
```

---

### Task 7: Docs + CLAUDE.md update

**Files:** Modify `CLAUDE.md`, `docs/superpowers/specs/2026-06-09-portal-retheme-design.md`

- [ ] **Step 1: Update the CLAUDE.md UX Design System section**

The existing "UX Design System — NEW THEME (2026-05-04)" section documents the Lux dual-palette. Add a superseding entry noting the Founders re-theme: blue `#266EA5` / green `#65BB84`, Plus Jakarta Sans + Merriweather, light+dark with device-default + `data-theme` toggle (localStorage `fp-theme`), tokens in `base.html :root`, semantic roles unchanged (`--ink`=bg, `--ivory`=text), `labels.html` still excluded. Add a Build Status line.

- [ ] **Step 2: Mark the spec implemented**

Set spec Status to `✅ Implemented`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-06-09-portal-retheme-design.md
git commit -m "docs: portal re-theme delivered; update design-system notes"
```

---

## Deployment (after merge)

Pure templates — no migration. Standard deploy:
```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal && git pull && systemctl restart founders-portal
```
Then hard-refresh (Ctrl+Shift+R) to clear cached CSS; verify the toggle in a real browser (light↔dark, persists across reload, no flash).

---

## Self-review notes (done while writing)

- **Spec coverage:** theming model (device default + override + pre-paint) → Tasks 2/3; light palette → T1; dark palette → T2; toggle UI sidebar footer → T4; tokens in base.html :root single source → T1/T2/T3; recap reconciliation → T5; light-polish + login + labels-excluded → T6; fonts swap/dedupe → T1(values)+T4(links); verification both modes → every task's screenshot step; docs → T7. ✅
- **Token-role preservation** called out as the top constraint (the documented invisible-text trap). ✅
- **Placeholder scan:** the polish pass (T6) is necessarily "fix what the screenshots show" — but the procedure is concrete (render list, the 4 specific checks, minimal edits), not a vague "handle edge cases." Acceptable for a CSS polish pass.
- **Naming consistency:** token names (`--ink/--surface/--gold/--green/--ivory/--slate/--border/--radius/--shadow*`), `data-theme` attribute, `localStorage 'fp-theme'`, `#themeToggle`, `.theme-toggle` used identically across tasks.
- **No tests to drift** (CSS) — the guardrail is the existing pytest suite staying green + rendered screenshots, stated per task.
- **Verification discipline** (screenshot both modes) baked into every visual task, per the lessons from the recap nesting/gradient bugs.
