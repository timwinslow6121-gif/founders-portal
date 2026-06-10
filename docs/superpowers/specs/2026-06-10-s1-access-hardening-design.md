# S1 — Access Hardening + Session Security (Design)

**Date:** 2026-06-10
**Milestone:** 1 (Security & Resilience) — pillar 2 of 5 (S0 backups ✅ done; this is S1)
**Status:** Design — approved, pending spec review → writing-plans
**Author:** brainstormed with Tim 2026-06-10

---

## 1. Context & threat model

The portal authenticates **exclusively via Google OAuth**, restricted to the
`@foundersinsuranceagency.com` Workspace domain (`app/auth.py`). **There is no
password login.** Therefore the classic "S1" playbook — rate-limit failed
passwords, lock the account after N attempts — **does not apply**: there is no
password for an attacker to brute-force. Google enforces credential
brute-force protection, MFA, and account lockout upstream.

The portal handles PHI/PII (names, DOB, MBI/Medicare numbers, addresses) and
money (commissions). The protections currently in place are: Google-domain
OAuth restriction, and HMAC signature verification on the comms webhooks. The
following are **completely absent today** and are the real S1 surface:

- **No session/cookie hardening.** No `SESSION_COOKIE_SECURE`, `HTTPONLY`,
  `SAMESITE`; no session timeout. `login_user(user, remember=True)` is called
  with **no `REMEMBER_COOKIE_DURATION`**, so Flask-Login defaults the remember
  cookie to **365 days**. A stolen/leaked session cookie therefore grants full
  access to all PHI/money for up to a year — and Google's MFA does nothing to
  stop it, because a replayed cookie never goes through Google.
- **No HTTP security headers.** No HSTS, CSP, X-Frame-Options,
  X-Content-Type-Options, Referrer-Policy.
- **No rate limiting** on the unauthenticated endpoints (login start, OAuth
  callback, comms webhooks) — availability/DoS exposure.

### Two-layer authentication model (why app-side session timeout is NOT redundant with Google's 12h reauth)

Tim confirmed (2026-06-10, Google Admin → Security → Google session control)
that Workspace reauthentication is set to **12 hours** — agents must re-login
with MFA every 12h. This is **not** redundant with the app-side session
timeout this spec adds; they protect different doors:

| Layer | Governs | Blind spot it has alone |
|---|---|---|
| **Google 12h + MFA** | *Getting an OAuth token issued* (identity proof at the Google login screen) | Useless once a **session cookie** is stolen — the attacker replays the cookie and never touches Google |
| **App 12h session** (this spec) | *Staying authorized inside the portal* once logged in — every page is authorized **solely by the Flask cookie**, the portal never re-contacts Google per-request | Useless against **password** theft — that is Google's job |

They cover each other's blind spots. Matching both to **12h** is a deliberate
UX choice: the agent experiences **one** clean daily ritual — a single morning
Google login + MFA establishes both a fresh Google token and a fresh 12h portal
session, with no double prompts and no mid-day surprise logout. The app-side
layer bounds the breach blast-radius of a stolen cookie from ~365 days to ≤12h.

### Guiding principle for all of S1

**Maximize real protection while changing agent behavior as little as
possible.** Security that frustrates the tech-averse agents (Betty/Brian/
Rebekah) gets worked around, and a worked-around control protects nothing. The
bar is: *invisible to honest users, expensive for attackers.* Every decision
below follows it.

---

## 2. Scope

**In scope (decided with Tim):**
- Session & cookie hardening (Secure/HttpOnly/SameSite, 12h absolute timeout,
  remember-me capped to 12h).
- HTTP security headers (HSTS, X-Frame-Options, X-Content-Type-Options,
  Referrer-Policy, a permissive-but-real CSP).
- Rate limiting on the unauthenticated endpoints via **Flask-Limiter
  (in-memory)**.
- `ProxyFix` so all of the above behaves correctly behind nginx.

**Explicitly out of scope (deliberately deferred or N/A):**
- Password lockout / failed-attempt throttling — no passwords exist.
- App-level lockout on repeated failed/non-domain OAuth callbacks — Google
  already gates this; low real value (Tim chose "Session + headers focus").
- Strict CSP with per-request nonces — deferred to a future task; would require
  touching base.html + ~26 templates with inline JS/CSS/handlers.
- Idle (last-activity) session timeout — Tim chose 12h absolute, no idle, to
  avoid mid-task logouts. No per-request activity tracking needed.
- Audit logging + breach alerting — that is **S2** (depends on this).
- Encryption-at-rest — that is **S3**.
- Redis-backed shared rate-limit storage — see §6 note; in-memory is sufficient
  at this scale (8 agents, 2 Gunicorn workers). Documented upgrade path.

---

## 3. Architecture

A single new module **`app/security.py`** exposing **`init_security(app)`**,
called once from `create_app()` in `app/__init__.py` (after `db.init_app` /
`login_manager.init_app`, consistent with the existing thin-registrar pattern).

`init_security(app)` wires four things:
1. **`ProxyFix`** — trust nginx's `X-Forwarded-Proto`/`-For` (1 hop) so Flask
   sees the real client IP and the real `https` scheme. Required for `Secure`
   cookies, HSTS, and correct rate-limit keying to work behind the reverse
   proxy.
2. **Session/cookie config** — set on `app.config` (§4).
3. **Security headers** — one `@app.after_request` handler (§5).
4. **Rate limiting** — a module-level `Limiter` instance initialized on the app
   (§6), with limits applied to the auth routes and the `/comms/webhook/*`
   paths.

No new model, **no migration** (12h timeout is cookie-lifetime config, not DB
state). New dependency: `flask-limiter`. Nothing moves out of `auth.py`; the
only change there is one line (§4).

---

## 4. Session & cookie hardening

Set in `init_security()` on `app.config`:

| Setting | Value | Why |
|---|---|---|
| `SESSION_COOKIE_SECURE` | `True` | Cookie only sent over HTTPS — never leaks over plain HTTP. |
| `SESSION_COOKIE_HTTPONLY` | `True` | JS can't read it — blocks XSS cookie theft. |
| `SESSION_COOKIE_SAMESITE` | `'Lax'` | Blocks CSRF on cross-site POSTs; `Lax` (not `Strict`) so the OAuth redirect back from Google still carries the session. |
| `PERMANENT_SESSION_LIFETIME` | `timedelta(hours=12)` | The 12h absolute timeout. |
| `REMEMBER_COOKIE_SECURE` | `True` | Same hardening for Flask-Login's remember cookie. |
| `REMEMBER_COOKIE_HTTPONLY` | `True` | " |
| `REMEMBER_COOKIE_SAMESITE` | `'Lax'` | " |
| `REMEMBER_COOKIE_DURATION` | `timedelta(hours=12)` | **Caps remember-me at 12h** so it cannot outlive the session and silently grant days of access. |

**The one behavioral change in `app/auth.py`:** for `PERMANENT_SESSION_LIFETIME`
to take effect the session must be marked permanent. In the `callback()` route,
immediately before `login_user(...)`, add:

```python
session.permanent = True
```

`login_user(user, remember=True)` is **kept** — but the remember cookie is now
hardened and capped at 12h, so "remember me" effectively means "stay logged in
for the 12h work day."

**Net effect:** every cookie is Secure + HttpOnly + SameSite=Lax, and every
session — remembered or not — expires 12h after login, forcing a fresh Google
login (with MFA) each morning. No idle tracking, no surprise mid-task logouts.

### Known Flask footguns this design pre-empts
- `PERMANENT_SESSION_LIFETIME` does **nothing** unless `session.permanent = True`
  is set at login. (Common mistake; explicitly handled above.)
- Flask-Login's remember cookie is a **separate** cookie from the session
  cookie. Without `REMEMBER_COOKIE_DURATION`, the 12h session expires but the
  (365-day default) remember cookie silently re-authenticates the user. Both
  cookies must agree on 12h or the timeout is an illusion. (Explicitly capped.)

---

## 5. HTTP security headers

One `@app.after_request` handler in `app/security.py` adds to every response:

| Header | Value | Protects against |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Protocol-downgrade / SSL-strip. **Emitted only when the (ProxyFix-corrected) request scheme is `https`**, so local `http://localhost:5000` dev is not poisoned with a year-long HTTPS-only directive. |
| `X-Frame-Options` | `DENY` | Clickjacking — portal cannot be iframed. |
| `X-Content-Type-Options` | `nosniff` | MIME-sniffing. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Stops MBI/customer IDs in URLs leaking to external sites via the `Referer` header when an agent clicks an outbound link. |
| `Content-Security-Policy` | *(string below)* | XSS / injected external resources / clickjacking backstop. |

**CSP string** (permissive-but-real — Tim's choice; allows existing inline
JS/CSS so nothing breaks, but locks down origins):

```
default-src 'self';
script-src 'self' 'unsafe-inline' https://accounts.google.com;
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com;
img-src 'self' data: https:;
connect-src 'self';
frame-ancestors 'none';
base-uri 'self';
form-action 'self' https://accounts.google.com;
```
(Emitted as a single-line header; shown multi-line here for readability.)

What this buys with **zero template rewrites**:
- `frame-ancestors 'none'` — clickjacking protection (reinforces X-Frame-Options).
- `default-src 'self'` + scoped `script/style/font-src` — an injected
  `<script src="evil.com">` won't load; only the portal origin + the
  Google/Google-Fonts hosts actually used are allowed.
- `'unsafe-inline'` **consciously kept** so the no-flash theme script (in
  `<head>` of base.html), the inline `onclick`/`onchange` handlers, and per-
  template `{% block styles %}` keep working. Tightening to nonces is a deferred
  future task (see §2 out-of-scope).
- `accounts.google.com` allowed in `script-src`/`form-action` so the OAuth login
  flow is not broken by the policy.

**Why `Referrer-Policy` matters most here:** customer-profile and lookup URLs
carry IDs in the path/query. Without a referrer policy, clicking any external
link from such a page hands the *full URL* (with the ID) to the destination via
`Referer` — a silent PHI leak. `strict-origin-when-cross-origin` strips
path/query when leaving the origin.

**Webhooks/JSON responses:** the comms webhooks return JSON; these headers are
harmless on them, so the handler applies globally with no exemption.

---

## 6. Rate limiting (Flask-Limiter, in-memory)

A `Limiter` instance in `app/security.py`, protecting **only the doors that
don't require a login** plus a generous per-agent backstop. A logged-in agent
never sees a limit during normal work — see the two-tier keying below, which
specifically handles the shared-office-IP case.

| Target | Limit | Keyed on | Rationale |
|---|---|---|---|
| Global default — **authenticated** traffic | `600/hour` | **logged-in agent** (`current_user.id`) | Everything an agent does once logged in (browse, send SMS, submit app). ~1 action / 6s sustained — far beyond real human pace. Per-agent keying means 4 agents in one office get **4 independent buckets**, not one shared bucket. |
| Global default — **unauthenticated** traffic | `200/hour` | client IP | Backstop for anonymous requests (pre-login). A script can't hammer the app; a human reaching the login page never approaches it. |
| `/auth/google` (start login) | `10/minute` | client IP | No human clicks "login" 10×/min. Stops OAuth-start spam. |
| `/auth/callback` (OAuth return) | `10/minute` | client IP | Throttles replaying/fuzzing the callback (e.g. hammering with non-Founders Google accounts). |
| **`/comms/webhook/*`** paths | `60/minute` | client IP | High enough for real carrier/VoIP bursts, low enough to blunt a flood. These already verify HMAC signatures — this is a second layer. (Webhooks are unauthenticated by nature, so IP-keyed is correct.) |

On limit exceedance Flask-Limiter returns a clean **HTTP 429** automatically.

### Two-tier key function (the shared-office-IP fix)

Rate limits are keyed by **a `key_func`**. The naive choice — always key on
client IP — has a real-world failure mode at Founders: most agents work alone in
their own office (own IP), but on some days **up to 4 agents share one office's
public IP** (NAT). A pure IP-keyed global limit would treat those 4 agents as a
**single user** and could throttle a legitimately busy AEP day.

The fix (a strict improvement, no security trade-off): a **two-tier
`key_func`** —

```python
def rate_limit_key():
    # Authenticated agent: key per-user so office-mates don't share a bucket.
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    # Pre-login / anonymous: IP is the only identity we have (and the abuse surface).
    return get_remote_address()
```

Result:
- **Authenticated traffic** is keyed per agent → 4 office-mates = 4 independent
  `600/hour` buckets; they can never starve each other, and no normal day comes
  near the ceiling.
- **Unauthenticated traffic** (`/auth/*`, `/comms/webhook/*`) stays IP-keyed —
  there is no logged-in identity there yet, and those are the actual abuse
  surface.

### Why legitimate agent activity is never slowed, missed, or interrupted

Agent actions and webhook traffic flow in **opposite directions**, so agent
actions are never on the throttled webhook path:

| Agent action | Actual request | Limit that applies |
|---|---|---|
| Sends an SMS | browser → `POST /comms/sms/send` (authenticated) → Twilio outbound | `600/hour` per-agent |
| Sends email | portal → Brevo (outbound API) | **none** (outbound) |
| Logs / takes a call | call *event* later arrives Quo → `POST /comms/webhook/quo` (Quo's server, not the agent) | `60/min` IP — never the agent |
| Submits an app | browser → authenticated portal route | `600/hour` per-agent |
| Browses customers all day | authenticated page loads | `600/hour` per-agent |

A 429 is only ever returned to whoever *exceeds* a limit; the limits are sized
so that is only ever an abusive script, never a human. Inbound webhooks that
arrive are **processed** — a limit cannot cause a webhook to be silently
dropped from the agent's perspective; it can only 429 a flood from one source
IP (and §6 "Tuning guard" says raise it if a real carrier burst ever 429s).

### Webhook rate-limit targeting — by URL path prefix, NOT by blueprint

The `comms` blueprint is **mixed**: it contains truly-public unauthenticated
webhooks **and** logged-in agent pages. Verified routes (2026-06-10):

- **Public webhooks** (`/comms/webhook/...`): `/webhook/quo`,
  `/webhook/calendly`, `/webhook/healthsherpa`.
- **Logged-in agent/admin pages** (must NOT be webhook-throttled):
  `/sms-templates`, `/sms-templates/create|approve|reject`, `/sms/send`,
  `/resolution`, `/resolution/<id>/link`, `/health`.

Therefore the `60/minute` webhook limit is applied by **URL path prefix
`/comms/webhook/`**, not by the blueprint and not by enumerating individual
routes. Consequences:
- All three current webhooks are covered today.
- **Convention (enforced going forward):** any future inbound webhook is named
  `/comms/webhook/<name>`. A future **Twilio SMS inbound** webhook added as
  `/comms/webhook/twilio` is then **automatically protected with zero S1
  rework**.
- The logged-in comms pages fall under the generous `200/hour` global like the
  rest of the app — admins clicking around the SMS-templates UI are never
  webhook-throttled.

### Twilio SMS & Brevo email — explicit handling (per Tim 2026-06-10)

- **Brevo email** is **outbound only** (`app/mailer.py` → Brevo REST API). There
  is no inbound Brevo endpoint in the portal. It needs **no rate-limit, no CSP
  rule, and no webhook exemption** (server-to-server `requests` call, not a
  browser fetch). Fully accounted for; nothing to add.
- **Twilio SMS** is currently **outbound** (SIP/SMS); there is **no Twilio
  inbound webhook route in the code today** — inbound voice events arrive via the
  Quo webhook. *If* a dedicated Twilio SMS inbound webhook is added later, the
  `/comms/webhook/` path-prefix rule above catches it the moment it is named per
  the convention. No S1 change required either way.

### In-memory storage caveats (stated honestly)
- In-memory = **per-worker** and **resets on restart**. With 2 Gunicorn workers
  the *effective* limit is ~2× the stated number (each worker counts its own
  buckets separately). This only makes the limits **more lenient**, never
  stricter — so it cannot cause a false throttle of an agent. Acceptable: these
  limits are abuse/DoS-blunting, not precise quotas.
- **Upgrade path:** swap the Limiter storage backend to Redis if exact,
  cross-worker limits are ever required. No code change beyond the storage URI.
- **Tuning guard:** `60/min` per source IP is comfortably above real
  Quo/Twilio/Calendly rates, but if a legitimate carrier burst ever 429s, raise
  it — never silently drop a commission/voice webhook. Likewise raise the
  per-agent `600/hour` if real usage (an admin loading overview + ledgers +
  recaps in one busy session) ever approaches it. Protecting agent workflow
  always wins over a tighter number.

---

## 7. Testing

`tests/test_security.py` (no VPS/venv needed; Flask test client):
- **Cookie flags:** after a simulated login, assert the session (and remember)
  cookie carry `Secure`, `HttpOnly`, `SameSite=Lax`.
- **Headers present:** a normal response carries
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy`, and a `Content-Security-Policy` containing
  `frame-ancestors 'none'` and `default-src 'self'`.
- **HSTS conditional:** HSTS present on an `https`-scheme request, absent on a
  plain `http` request.
- **Rate limit 429:** hammering `/auth/google` past `10/minute` yields HTTP 429.
- **Per-agent keying:** the `key_func` returns `user:<id>` for an authenticated
  request and the IP for an anonymous one — assert both branches (the
  shared-office-IP fix; ensures two different logged-in agents don't share a
  bucket even from the same IP).
- **Session permanence:** `PERMANENT_SESSION_LIFETIME` is configured to 12h and
  the callback marks the session permanent (assert via app.config + a login
  flow check or a unit check on the config values).

Full suite (`python3 -m pytest -q`, currently ~180 passing) must stay green.

---

## 8. Deployment notes

- New dependency: add `flask-limiter` to `requirements.txt`. On VPS install via
  `./venv/bin/pip install -r requirements.txt` (never plain pip).
- **No migration** — nothing to `flask db upgrade`.
- After deploy, verify: agents are NOT logged out mid-day; the morning after,
  a fresh Google login is required (12h elapsed). Confirm the portal still loads
  (CSP didn't break the theme script / inline handlers) in **both light and dark
  mode**, and that the Google login flow completes (CSP allows
  `accounts.google.com`).
- nginx already terminates TLS and sets `X-Forwarded-Proto`; confirm ProxyFix
  sees it so `Secure`/HSTS engage. (If HSTS or Secure cookies misbehave, the
  ProxyFix hop count or an nginx header is the first thing to check.)

---

## 9. Summary of changes

- **New:** `app/security.py` (`init_security(app)` — ProxyFix, session config,
  headers handler, Limiter).
- **New:** `tests/test_security.py`.
- **Edit:** `app/__init__.py` — call `init_security(app)` in `create_app()`.
- **Edit:** `app/auth.py` — add `session.permanent = True` before `login_user`
  in `callback()`.
- **Edit:** `requirements.txt` — add `flask-limiter`.
- **No model, no migration.**

This is pillar 2 of Milestone 1 (Security & Resilience). S2 (audit log + breach
alerting) builds on this — S2's alerts will consume the rate-limit/lockout
events surfaced here.
