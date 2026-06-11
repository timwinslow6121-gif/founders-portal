# Founders Login Redesign — LOCKED design (2026-06-10)

Designed via visual-companion prototyping with Tim. **Final prototype:** `.superpowers/brainstorm/27364-1781142680/content/login-v5.html` (+ color/glow tuners). This file records the locked DECISIONS so the production `app/templates/login.html` build is faithful. This is part of Milestone 2 / Phase 1 (design system); the login is the system's "character" showpiece.

## Concept
A single **frosted-glass card** centered on a **full-bleed animated blue→green gradient**. Everything lives in the one card (no split layout). The card establishes the portal's personality; the rest of the portal stays calm/refined (login is the one place character belongs — no data, no task, a threshold moment).

## The logo (NEW, reusable asset)
- Source: `docs/FoundersIns_Logo_Color_OnLight.eps` → converted to SVG (Inkscape). The **icon** (mortar+pestle in a hand, ringed) is 4 vector paths, separable for animation:
  - `p-hand` = blue ring + cradling hand (fill #306ea9 → rendered **white** on the gradient).
  - `p-bowl` = mortar bowl body (green #67be77 → rendered **#f3fff7**).
  - `p-rim`  = the horizontal rim bar (green).
  - `p-pestle` = the pestle knob+stem — **the animated grinder** (green).
- viewBox `0 0 97 97` with wrapper `<g transform="matrix(1.3333333,0,0,-1.3333333,0,97.013333)"><g transform="scale(0.1)">` (the EPS→SVG coordinate flip+scale; keep it).
- **Action item for production:** save the clean icon SVG as a reusable asset (e.g. `app/static/img/founders-mark.svg`) and use it crisp everywhere (login big, sidebar small, recap). Replaces the giant 2560px PNG.

## Animation (the "character") — total intro ~1.6s, then a perpetual idle
Sequence on load (respect `prefers-reduced-motion` → all static, logo fully shown):
1. **Card** fades+rises in (`cardIn`, .55s @ .05s).
2. **Title** fades up (@ .25s).
3. **Hand/ring** scale+fade in — clean reveal, NO stroke-draw (stroke-draw caused the "cut-off/flat" hand bug — do not reintroduce it).
4. **Bowl** then **rim** rise in (@ .8s / .92s).
5. **Pestle** drops in with a spring (`pestleIn` cubic-bezier(.34,1.56,.64,1) @ 1.1s), THEN **grinds forever** — `grind` 2.8s ease-in-out infinite: a subtle rock+dip (`translate(±2.5px,1.5px) rotate(±7deg)`), `transform-origin:50% 95%`. **This compounding motion is the soul** — it's the Cannon Pharmacy origin (Brian co-founded Cannon Pharmacy in Kannapolis; Founders grew from it). Keep it subtle + perpetual.
6. Welcome/sub/button/fine fade up in sequence (1.0–1.3s).

## Layout inside the card (top → bottom), roomy vertical spacing
1. **Title** — two lines, Merriweather 900, 30px, centered:
   - Line 1: **FOUNDERS** (all caps), `letter-spacing:0.10em` (LOCKED — optically width-matched to line 2; erring slightly wide is intentional).
   - Line 2: **Agent Portal** (Merriweather 900, 30px, `white-space:nowrap`).
   - Both lines **white**. **Navy glow** text-shadow = the "Strong glow" (option C):
     `text-shadow:0 1px 2px rgba(0,28,52,.7), 0 3px 10px rgba(0,30,60,.6), 0 6px 30px rgba(0,30,60,.55);`
     (Tim liked B-or-C; C chosen. B = `0 2px 4px rgba(0,30,55,.55),0 4px 22px rgba(0,30,55,.5)` if C ever feels heavy.)
   - **Do NOT** color the lines navy as a fill (muddy on the bluish glass) — white fill + navy GLOW is the effect Tim wanted.
   - The logo's own wordmark text is DROPPED (the big title replaces it — no doubling).
2. **Animated logo** (~150px), margin-top ~22px.
3. **"Welcome back"** (Merriweather 700, ~19px) — extra gap above it (margin-top ~26px) per Tim.
4. **"Sign in to continue"** sub.
5. **Google "Sign in with Google"** button (white, real Google G svg, soft shadow, hover lift).
6. **Fine print:** "Restricted to @foundersinsuranceagency.com accounts."

## Card + background spec
- Card: `width ~392px`, `background:rgba(255,255,255,.15)`, `backdrop-filter:blur(24px) saturate(140%)`, `border:1px solid rgba(255,255,255,.45)`, `border-radius:22px`, `padding:42px 38px 46px`, `box-shadow:0 24px 64px rgba(0,20,40,.42), inset 0 1px 0 rgba(255,255,255,.55)`.
- Gradient (the recap "new customers" gradient, extended to a true journey): `linear-gradient(135deg,#1B5380 0%,#266EA5 28%,#3E8FA0 52%,#65BB84 78%,#79C795 100%)`, `background-size:260% 260%`, **animated** `wave` 14s (pans background-position 0%→100%→0% with vertical wander) so it gently waves like water. NOTE: do NOT use the soft-light blob overlay from earlier drafts — it washed the blue to all-green. The waving multi-stop gradient + one faint radial `sheen` (16s drift) is the final treatment.
- Logo lift: white logo + `filter:drop-shadow(0 6px 20px rgba(0,28,54,.4))` (NOT a frosted disc behind it — the disc covered the title and was cut).

## Brand notes worth keeping
- The two brand colors: blue **#266EA5**, green **#65BB84** (logo's own #306ea9/#67be77 are near-identical; use the portal tokens).
- Tagline idea surfaced (variant B): "Caring for our community's health, one plan at a time." — NOT used on login, but captured if wanted elsewhere. Real tagline TBD with Tim/Brian.

## Build target
Production file: `app/templates/login.html` (standalone, its own `:root`/styles today). Rebuild it to this design using the portal's Phase-1 design tokens where they apply (fonts, the blue/green, radius scale). Keep it standalone (it doesn't extend base.html). Reduced-motion fallback required.
