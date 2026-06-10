# S2 — Audit Log + Breach Alerting (Design)

**Date:** 2026-06-10
**Milestone:** 1 (Security & Resilience) — pillar 3 of 5 (S0 backups ✅, S1 access hardening ✅; this is S2)
**Status:** Design — approved, pending spec review → writing-plans
**Author:** brainstormed with Tim 2026-06-10

---

## 1. Context & goal

Tim's north star, in his words: *"Log every access/login/data-view/export
(who-what-when); notify me ASAP + the extent of the breach."* And the governing
constraint, also his words: *"I don't want to drown in noise — only actionable
intel I can understand and use to protect the portal."*

S2 builds on the now-deployed S0 (backups) and S1 (access hardening). S1 created
new security-relevant events (rate-limit 429s, the login flow) but **nothing
logs them today**. There is an existing `AuditLog` model, but it is a *business*
audit log: it only records carrier uploads, and only carries
`user_id / action / detail / created_at` — it lacks the forensic fields a breach
investigation needs (IP, user-agent, agency_id) and is written by hand in two
places in `upload.py`.

S2 turns that into a real security audit trail + a tightly-scoped alerting layer.

### The two-stream principle (this is the anti-noise guarantee)

S2 has TWO separate streams, and only ONE may interrupt Tim:
- **Audit log (DB):** the quiet, complete record. Captures security + sensitive-
  data events for later investigation. Tim never has to read it day-to-day.
- **Alerts (email):** the loud stream. Fires ONLY on three outsider-flavored
  triggers that basically never happen during honest 9–5 agent work.

**Log everything (in scope); alert on almost nothing.** Drowning in noise is
prevented by construction: noise goes silently to the log; only the three
anomalous triggers reach the inbox, and even those are de-duplicated.

---

## 2. Decisions (locked with Tim 2026-06-10)

**Canonical `action` strings** (use these EXACT values at hook points so the
viewer/filters/alert rules agree): `login_success`, `login_failed`,
`login_nondomain`, `logout`, `rate_limit_blocked`, `customer_view`,
`customer_export_csv`, `labels_pdf_download`, `agent_role_change`,
`carrier_upload`.

**Log scope — security + sensitive-data events** (NOT every request):
- Auth: login success, login failure, non-domain login attempt, logout.
- Security: S1 rate-limit 429 hits.
- Data access: customer profile views (PHI read accountability).
- Export: CSV export, birthday-labels PDF download.
- Admin: role/contract changes (agent settings).
- Business: the 2 existing carrier-upload logs (migrated to the new helper).

**Alert triggers — three only** (Tim deliberately EXCLUDED "new device/new
location" as too noisy — agents travel/switch networks; insider-flavored = false
positives):
1. Non-domain / failed login attempt.
2. Off-hours bulk export (CSV/PDF outside normal work hours).
3. Repeated rate-limit hits (429 flood) from one source.

**Alert channel — email via Brevo** (existing `app/mailer.py`; zero new infra).

**Storage — extend the existing `AuditLog`** (one unified trail, one
`log_event()` helper). Add forensic columns + a `category`/`severity` split so
security events stay filterable.

**Viewer — admin-only `/admin/audit-log` page** with filters (the "extent" tool).

**Deliverable beyond code — `docs/INCIDENT_RESPONSE_RUNBOOK.md`**: Tim's plain-
English action plan ("what do I actually DO when an alert fires"). Drafted with
Tim near the end of the build.

---

## 3. Architecture

Three cooperating modules, each with one responsibility:

### 3.1 `app/audit.py` — the seam
One function is the ONLY place that writes `AuditLog`:

```python
def log_event(action, *, category, detail=None, user=None,
              customer_id=None, severity="info"):
    """Capture request context + write one AuditLog row, then maybe alert."""
```

Responsibilities:
- Capture request context: `ip_address` (from `request.remote_addr` — S1's
  ProxyFix already makes this the REAL client IP, not nginx), `user_agent`
  (`request.user_agent.string`, truncated to 256), `agency_id` (from `user` or
  `current_user`), and the acting `user_id` (nullable — see §4).
- INSERT one `AuditLog` row. Never UPDATE/DELETE (append-only by convention).
- Hand the row to `app.alerts.maybe_alert(row)` for the alert decision.
- Be safe to call outside a request context (e.g. a CLI script) and safe if the
  mailer fails — **logging an event must never raise into the caller's flow**
  (wrap alert dispatch in try/except; a failed alert must not lose the log row
  or break the user's request).

This is the same seam pattern as `app/security.py` (init_security) and
`app/plan_provenance.py`: one helper guarantees every event captures the
forensic fields identically. Hand-rolled `AuditLog(...)` at each call site would
eventually forget the IP — and that is the row you need during a breach.

### 3.2 `app/alerts.py` — the alert rules + email
```python
def maybe_alert(audit_row):
    """Apply the 3 trigger rules; on a match, compose + send a de-duped,
    plain-English email via app.mailer.send_email."""
```
Responsibilities:
- Decide whether `audit_row` matches one of the three triggers (§5).
- **De-duplicate / throttle:** one summary email per (trigger, source) per time
  window (default 5 min) — a 429 flood yields ONE email with a count, not N.
  Throttle state is a simple in-process dict keyed by (trigger, ip/user),
  last-sent timestamp (per-worker is fine; worst case is 2× emails across 2
  gunicorn workers — acceptable, still not a flood).
- Compose the plain-English email (§6) and send via `app.mailer.send_email` to
  `MAIL_FROM` (admin@). No DB writes of its own.
- Be the single place alert *rules* live, so they can change without touching
  logging.

### 3.3 Extended `AuditLog` model + `/admin/audit-log` viewer
Migration 025 (§4) + a read-only admin viewer (§7).

### 3.4 Hook points (thin one-liners)
`log_event(...)` is called at ~10 sites (§7). No business logic moves; each is a
single line added at the right place.

---

## 4. Data model — extended `AuditLog` (migration 025)

Existing columns stay (`id`, `user_id`, `action`, `detail`, `created_at`). ADD,
all nullable so the existing two upload-log writes keep working:

| New column | Type | Purpose |
|---|---|---|
| `ip_address` | `String(45)` | Client IP (45 fits IPv6). The REAL client IP via S1 ProxyFix. "From where." |
| `user_agent` | `String(256)` | Browser/device string (truncated). "What device." |
| `agency_id` | `Integer`, FK→agencies.id, indexed | Multi-tenant scoping — the audit log must be scoped like every other table. |
| `category` | `String(32)`, indexed | `auth` \| `data_access` \| `export` \| `admin` \| `security` \| `business`. Drives viewer + alert filtering. |
| `severity` | `String(16)` | `info` \| `warning` \| `alert`. `alert` = an alert email fired for this row. |

**`user_id` stays nullable — deliberately.** The most important auth events have
NO valid user: an outsider trying `attacker@gmail.com`, or a failed attempt.
Those rows carry the attempted email in `detail` and a null `user_id`. A schema
requiring `user_id` would blind the system to exactly the probing it most needs
to see.

**Append-only guarantee (S2 commitment):** `log_event()` only ever INSERTs;
nothing in the codebase UPDATEs or DELETEs audit rows; the viewer is read-only.
An audit log an attacker can edit is worthless. (DB-level immutability triggers
are an S3/S4 concern; the S2 commitment is convention + no-mutation code.)

`created_at` is used as the event timestamp; "off-hours" is computed from it (§5).

---

## 5. Alert trigger rules (the three)

Evaluated in `maybe_alert(row)`:

1. **Non-domain / failed login** — `category == "auth"` and `action in
   ("login_failed", "login_nondomain")`. Severity `alert`. Always alerts (rare,
   outsider-flavored). `login_success`/`logout` are logged but never alert.

2. **Off-hours bulk export** — `category == "export"` AND `created_at` (in the
   agency's local timezone, **America/New_York** — Founders is western NC) falls
   OUTSIDE business hours. Business hours default: **Mon–Fri 7:00 AM–7:00 PM
   ET**; anything else (nights, weekends) is off-hours. Severity escalated to
   `alert` for the email; the underlying export row is still logged `info`
   regardless of time.

3. **429 flood** — `category == "security"` (a 429 hit) where the same source
   (ip or user key) has produced ≥ N 429s within the window (default **N=5 in
   5 min**). Severity `alert`. De-dup ensures ONE summary email per source per
   window, carrying the count.

**De-dup/throttle (applies to all three):** one email per (trigger, source-key)
per 5-min window. This is the single most important anti-noise rule — the
429-flood trigger by definition produces a burst, and must page Tim a handful of
times with a count, never hundreds of times.

Thresholds (`OFF_HOURS_*`, `FLOOD_COUNT`, `FLOOD_WINDOW`, `ALERT_THROTTLE_WINDOW`)
are module constants in `alerts.py` so they're tunable in one place.

---

## 6. The alert email — plain-English, actionable

Every alert answers four questions in plain language, written so a non-security
person acts immediately:

```
🔔 Founders Portal Security Alert

What happened:  Someone tried to log in with a non-Founders Google account.
Who / where:    attempted randomguy@gmail.com — from IP 203.0.113.9 —
                Chrome on Windows.
When:           2026-06-10 at 11:42 PM ET (off-hours).
Access granted? NO — the portal blocked it (only @foundersinsuranceagency.com
                can get in).
What it means & what to do:  An outsider may be probing the login. No action
                needed — it was already blocked. If you see many of these from
                the same IP, that IP is worth blocking at the firewall (see the
                Incident Response Runbook).
```

Design rules that keep alerts actionable, not alarming:
- **Every alert states whether access was actually granted or blocked** — so Tim
  instantly knows "already handled" vs "act now." Most are "blocked, FYI."
- **Plain-English "what it means"** — no raw logs, no jargon.
- **A concrete "what to do," or explicitly "nothing needed"** — never a dead end;
  links to the runbook for the act-now cases.
- **De-duped** so a flood is one summary email, not a hundred.

The three messages:
1. Non-domain/failed login → "outsider tried to get in; was blocked" (or "a
   teammate's login failed").
2. Off-hours export → "a CSV/PDF export of customer data happened at [time]
   outside work hours by [agent] from [IP] — if that was them, fine; if not,
   their account may be compromised → runbook."
3. 429 flood → "one source is hammering the portal (possible bot/attack); S1 is
   auto-blocking it; here's the IP and count → runbook if it persists."

---

## 7. Viewer, hook points, testing

### 7.1 Admin viewer — `/admin/audit-log`
- Admin-only (existing `if not current_user.is_admin: abort(403)` pattern).
- Newest-first, paginated table: time, user (or attempted email), action,
  category, severity, IP, user-agent.
- Filters: user, category, severity, date range. Alert-severity rows highlighted.
- Read-only (no edit/delete — append-only guarantee). agency_id-scoped.
- This is the "extent" tool: when an alert fires, filter to one IP/user and see
  everything it touched (e.g. every customer a possibly-compromised account
  viewed).

### 7.2 Hook points (thin `log_event(...)` calls)
- `app/auth.py`: login success (`auth`/info); failed + non-domain login
  (`auth`/alert, null user, attempted email in detail); logout (`auth`/info).
- `app/security.py`: 429 hit (`security`/warning) — via Flask-Limiter's
  `on_breach` / a 429 error handler, logging ip + endpoint.
- `app/customers.py`: profile view — hook the main GET view function for
  `/customers/<int:customer_id>` (customers.py:466), action `customer_view`,
  `data_access`/info, with `customer_id` (log once per page load, after access
  is granted — both current-AOR and former-AOR reads count; do NOT log the
  POST sub-routes like /notes, /field separately); CSV export at
  `/customers/export`, action `customer_export_csv`, `export`/info.
- `app/labels.py`: PDF download at `/birthday-labels/download` (`export`/info).
- `app/agent_settings.py`: role/contract change (`admin`/warning).
- `app/upload.py`: migrate the 2 existing `AuditLog(...)` writes to
  `log_event(action="carrier_upload", category="business", ...)`.

**PHI-accountability keystone:** logging the customer-profile *view* (a read,
not just a write) at `customers.py:466` is what lets a breach investigation
answer "exactly which records did this account see." One line; the line that
makes the system worth having.

### 7.3 Testing — `tests/test_audit.py` (SQLite in-memory, mailer mocked)
- `log_event()` writes a row capturing ip/user_agent/agency_id/category/severity.
- Failed/non-domain login → row with null `user_id` + attempted email in detail.
- Off-hours export → alert fires; business-hours export → NO alert (mock the
  clock / pass a fixed timestamp).
- 429 flood → throttled to ONE alert across N events (assert mailer call count).
- Non-domain login → alert fires.
- Viewer: admin → 200 + filters narrow results; non-admin → 403.
- `log_event` never raises if the mailer fails (mailer raises → caller unaffected,
  row still written).
- Existing upload tests still pass after the `log_event()` migration.

---

## 8. Deliverable — `docs/INCIDENT_RESPONSE_RUNBOOK.md`

Tim's plain-English action plan, drafted WITH Tim near the end of the build (he
explicitly wants to talk through "what do I actually do"). Covers, per alert
type:
- What the alert means (restated).
- Immediate triage: was access granted? (the email already says).
- Concrete lockdown actions: revoke a user's Google session (Workspace admin →
  Users → sign out), block an IP at nginx/firewall, force portal re-login
  (rotate `SECRET_KEY` → all sessions invalidated), disable a compromised
  agent's portal access.
- How to use the `/admin/audit-log` viewer to scope "the extent."
- Who to call / escalation + the HIPAA-breach consideration (PHI exposure has
  reporting obligations — note it, don't pretend to give legal advice).

This runbook is the written form of the "what to do" each alert links to.

---

## 9. Out of scope (deferred)

- "New device / new location" alert trigger (Tim excluded — too noisy now; the
  audit log will accumulate the IP/UA history that could make it smarter later).
- SMS alerts (email-only now; `app/alerts.py`'s single dispatch point makes an
  SMS channel a clean future add).
- Per-customer "who viewed this" trail on the profile page (viewer page covers
  investigation now; this is a later PHI-accountability enhancement).
- DB-level append-only triggers / log shipping off-box (S3/S4 hardening).
- Log retention/rotation policy (volume is low at this scope — security+sensitive
  events for 8 agents; revisit if the table grows large).

---

## 10. Summary of changes

- **New:** `app/audit.py` (`log_event` seam), `app/alerts.py` (3 rules +
  de-duped plain-English email), `tests/test_audit.py`,
  `docs/INCIDENT_RESPONSE_RUNBOOK.md`.
- **New:** `/admin/audit-log` viewer route + template (admin blueprint /
  `routes.py` pattern) + nav entry (admin only).
- **Migration 025:** extend `audit_logs` with ip_address, user_agent, agency_id,
  category, severity.
- **Edit:** `app/auth.py`, `app/security.py`, `app/customers.py`,
  `app/labels.py`, `app/agent_settings.py` — thin `log_event(...)` hooks;
  `app/upload.py` — migrate 2 existing writes.
- **No new dependency.**

Pillar 3 of Milestone 1. Builds on S1 (consumes its 429 events + ProxyFix IP).
S3 (encryption-at-rest) and S4 (pentest) follow. See [[roadmap-2026-06-09]],
[[s3-encryption-preview]], and the S1 spec.
