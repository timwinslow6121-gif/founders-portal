# Founders Portal — Full Project Audit
## Date: March 25, 2026
## Purpose: Reconcile CLAUDE.md, FOUNDERS_PORTAL_CONTEXT.md, PRODUCT_VISION.md
##           against SESSION_UPDATE_2026-03-24.md (authoritative decisions)

---

## HOW TO USE THIS DOCUMENT

1. **Read this first** before opening a Claude Code session
2. Update each file in order: CLAUDE.md → FOUNDERS_PORTAL_CONTEXT.md → PRODUCT_VISION.md
3. After all three are updated, commit and push to GitHub
4. Feed this audit doc + SESSION_UPDATE_2026-03-24.md to Claude Code as context

---

## SEVERITY LEGEND

🔴 CRITICAL — Will cause Claude Code to build the wrong thing
🟡 STALE — Outdated decision that needs updating
🟢 MINOR — Cosmetic/organizational inconsistency

---

## AUDIT FINDINGS

---

### 🔴 CRITICAL #1 — Wrong Phone System in ALL Three Files

**What the files say:**
- CLAUDE.md line: `OpenPhone for SMS/calls (Phase 3)`
- CLAUDE.md Phase 3 checklist: Entire section is OpenPhone setup steps
- FOUNDERS_PORTAL_CONTEXT.md Section 3: OpenPhone listed as the telephony decision
- FOUNDERS_PORTAL_CONTEXT.md Section 14: `Missed call → OpenPhone auto-reply SMS`
- FOUNDERS_PORTAL_CONTEXT.md Section 17: Phase 3 pre-code lists OpenPhone setup
- FOUNDERS_PORTAL_CONTEXT.md Section 18 notes: `OpenPhone chosen over RingCentral (decision 2026-03-20)`
- FOUNDERS_PORTAL_CONTEXT.md Phase 3 webhook: `comms/webhook/openphone`
- PRODUCT_VISION.md Section 7: `RingCentral API` listed as third-party API (High priority)
- PRODUCT_VISION.md Add-on pricing: `Communication Hub: RingCentral + Calendly + auto-reply`
- PRODUCT_VISION.md Phase 4: `RingCentral integration` listed first

**What SESSION_UPDATE says (authoritative):**
- **Dialpad** is the primary agent-facing phone system ($15/user/mo)
- **Retell AI** handles missed calls via SIP forwarding from Dialpad
- **Twilio** is utility layer only (automated SMS, Retell SIP trunking)
- OpenPhone was never in the session — this was an older decision from before the
  Gemini session, which itself chose Twilio, which was then updated to Dialpad+Twilio
- RingCentral is what's being REPLACED, not integrated

**Required changes:**

CLAUDE.md:
- Line: `SendGrid for email, OpenPhone for SMS/calls (Phase 3)`
  → `SendGrid for email, Dialpad for SMS/calls, Retell AI for missed call handling (Phase 3)`
- Phase 3 Pre-Code Checklist: DELETE entire OpenPhone section
  → Replace with Dialpad setup checklist (see SESSION_UPDATE Section 1)
- Phase 3 webhook: `comms/webhook/openphone` → `comms/webhook/dialpad`

FOUNDERS_PORTAL_CONTEXT.md Section 3 (Tech Stack table):
- Row 2: `OpenPhone | SMS + telephony | Decision made 2026-03-20`
  → `Dialpad | SMS + telephony + AI missed call | Decision made 2026-03-24`
- Row 3: `VOXO | SMS + telephony (some agents) | Replace with OpenPhone`
  → `VOXO | SMS + telephony (some agents) | Replace with Dialpad`
- Add new row: `Retell AI | AI receptionist for missed calls | New addition`
- Add new row: `Twilio | Utility SMS + Retell SIP trunking | Edge cases only`

FOUNDERS_PORTAL_CONTEXT.md Section 14:
- `Missed call → OpenPhone auto-reply SMS → Calendly booking link`
  → `Missed call → Retell AI (via Dialpad SIP) → books appointment or takes message`

FOUNDERS_PORTAL_CONTEXT.md Section 17 Phase 3 Pre-Code:
- Delete all OpenPhone references
- Replace with:
  ```
  - [ ] Sign up for Dialpad — sign BAA immediately from Admin Portal
  - [ ] Provision Dialpad numbers for each pilot agent
  - [ ] Store DIALPAD_API_KEY, DIALPAD_WEBHOOK_SECRET in VPS .env
  - [ ] Register webhook: https://portal.foundersinsuranceagency.com/comms/webhook/dialpad
        Events: call.completed, call.missed, message.received, message.sent
  - [ ] Set up Retell AI account — sign BAA at click-agreements.retellai.com
  - [ ] Configure Retell agent for Medicare appointment booking + message taking
  - [ ] Configure Dialpad SIP forwarding to Retell when agent unavailable
  - [ ] Test: call Dialpad number while unavailable → verify Retell answers
  ```

FOUNDERS_PORTAL_CONTEXT.md Section 18 notes:
- `OpenPhone chosen over RingCentral (decision 2026-03-20)` → DELETE
  → Add: `Dialpad chosen as primary phone system (decision 2026-03-24, supersedes OpenPhone)`
  → Add: `Retell AI chosen as missed call handler (decision 2026-03-24)`
  → Add: `Twilio is utility layer only — NOT the phone system`

PRODUCT_VISION.md Section 5 Add-ons:
- `Communication Hub | $99 | RingCentral + Calendly + auto-reply + SMS campaigns`
  → `Communication Hub | $99 | Dialpad + Retell AI + Calendly + auto-reply + SMS campaigns`
- DELETE: `Fireflies Integration | $29 | Meeting summaries → customer records automatically`
  (Fireflies eliminated — replaced by Google Meet native recording, $0 cost)

PRODUCT_VISION.md Section 7 Third-Party APIs table:
- DELETE: `RingCentral API | Call logs, SMS, webhooks | Existing subscription | High`
- DELETE: `Fireflies.ai API | Meeting summaries webhook | Existing subscription | Medium`
- ADD: `Dialpad API | Call logs, SMS, webhooks, AI summaries | $15/user/mo | High`
- ADD: `Retell AI | AI missed call handler, appointment booking | $0.07-0.08/min | High`
- ADD: `Google Meet REST API | In-person recording + transcript | $0 (Workspace) | High`
- ADD: `Google Workspace Events API | Transcript webhook trigger | $0 (Workspace) | High`
- ADD: `HealthSherpa API | Enrollment data webhooks | Free | High`

PRODUCT_VISION.md Phase 4 (Communication Hub):
- `RingCentral integration` → `Dialpad integration`
- `Agency-wide RingCentral standardization` → `Agency-wide Dialpad standardization`
- `Fireflies.ai webhook → meeting summary → customer record`
  → `Google Meet transcript webhook → Claude API → meeting summary → customer record`

---

### 🔴 CRITICAL #2 — Fireflies Listed as Active in All Three Files

**What the files say:**
- CLAUDE.md: No Fireflies reference (good)
- FOUNDERS_PORTAL_CONTEXT.md Section 3: Row 15: `Fireflies.ai | Meeting recording + AI summaries | Tim only | Integrate via webhook`
- FOUNDERS_PORTAL_CONTEXT.md Section 17 Phase 3 code: `Fireflies webhook — meeting summary → CustomerNote (meeting_summary)`
- FOUNDERS_PORTAL_CONTEXT.md Section 18 notes: `Fireflies.ai already in Tim's workflow — webhook integration in Phase 3`
- PRODUCT_VISION.md Section 5: `Fireflies Integration | $29 | Meeting summaries → customer records`
- PRODUCT_VISION.md Section 7: `Fireflies.ai API | Meeting summaries webhook | Existing subscription | Medium`
- PRODUCT_VISION.md Phase 4: `Fireflies.ai webhook → meeting summary → customer record`

**What SESSION_UPDATE says (authoritative):**
Fireflies ELIMINATED. BAA Enterprise-only ($40/user/mo) + Private Storage required.
Replaced by Google Meet native recording + Google Workspace Events API webhook.
Cost: $0 additional. BAA already covered by Google Workspace Business Plus.

**Required changes:** (see Critical #1 above for specific line changes — all Fireflies
references need to be replaced with Google Meet native recording architecture)

FOUNDERS_PORTAL_CONTEXT.md Section 3:
- Row 15: `Fireflies.ai | Meeting recording + AI summaries | Tim only | Integrate via webhook`
  → DELETE and replace with:
  `Google Meet native | In-person meeting recording + transcript | All agents | Integrate via Workspace Events API`

FOUNDERS_PORTAL_CONTEXT.md Section 17 Phase 3 code:
- `Fireflies webhook — meeting summary → CustomerNote (meeting_summary)`
  → `Google Meet Workspace Events webhook → transcript → Claude API → CustomerNote`

FOUNDERS_PORTAL_CONTEXT.md Section 18:
- `Fireflies.ai already in Tim's workflow — webhook integration in Phase 3` → DELETE
  → Add: `Fireflies eliminated — BAA Enterprise-only. Google Meet native recording replaces it ($0).`
  → Add: `Google Meet unique space created per appointment via REST API — never shown to customer`
  → Add: `Workspace Events API fires webhook when transcript ready → portal matches by Meet space ID`

---

### 🔴 CRITICAL #3 — Phase 2 Marked as "Next Up" in PRODUCT_VISION.md

**What PRODUCT_VISION.md says:**
Phase 2 section header: `🔜 Phase 2 — Customer Master (Next)`
And lists all Phase 2 features as planned/future.

**Reality:**
Phase 2 is COMPLETE as of 2026-03-20 per FOUNDERS_PORTAL_CONTEXT.md Section 17.
All Customer Master features are built and live.

**Required change in PRODUCT_VISION.md Section 6:**
- `🔜 Phase 2 — Customer Master (Next)` → `✅ Phase 2 — Customer Master (Complete — 2026-03-20)`

---

### 🔴 CRITICAL #4 — Phase 2.5 PostgreSQL Migration Missing Everywhere

**What the files say:**
- CLAUDE.md: `SQLite (dev/prod) → PostgreSQL (planned for white-label)`
  Implies PostgreSQL is a distant future concern, not an immediate blocker.
- FOUNDERS_PORTAL_CONTEXT.md Section 17 Roadmap: No Phase 2.5 listed at all.
  Goes directly from Phase 2 complete to Phase 3 next.
- PRODUCT_VISION.md: PostgreSQL migration listed under Phase 8 (White Label) only.

**What SESSION_UPDATE says (authoritative):**
Phase 2.5 is a NEW PHASE and a HARD PREREQUISITE before any Phase 3 code is written.
The multi-tenant agency_id architecture must be built into PostgreSQL from scratch.
Nothing in Phase 3 begins until Phase 2.5 is complete.

**Required changes:**

CLAUDE.md Build Status:
```
- **Phase 1 ✅** — BOB parsers, commission audit, etc.
- **Phase 2 ✅** — Customer master (complete 2026-03-20)
- **Phase 2.5 🔜** — PostgreSQL migration (HARD PREREQUISITE for Phase 3)
  - Install PostgreSQL on VPS
  - Add agency_id FK to every table (multi-tenant from day one)
  - Migrate from SQLite → PostgreSQL
  - Run flask db upgrade, verify data integrity
  - Remove SQLite dependency
- **Phase 3 ⏳** — Communications Hub (blocked until Phase 2.5 complete)
```

FOUNDERS_PORTAL_CONTEXT.md Section 17 Roadmap:
- Insert Phase 2.5 between Phase 2 and Phase 3 with same content as above

PRODUCT_VISION.md Section 6:
- Move PostgreSQL migration from Phase 8 to a note after Phase 2 marked complete:
  `Note: PostgreSQL migration (Phase 2.5) is a hard prerequisite before Phase 3.
   Multi-tenant agency_id architecture must be built in from day one, not retrofitted.`

---

### 🔴 CRITICAL #5 — CLAUDE.md Stack Lists Wrong Database Upgrade Path

**What CLAUDE.md says:**
`SQLite (dev/prod) → PostgreSQL (planned for white-label)`

**What SESSION_UPDATE says:**
PostgreSQL migration is Phase 2.5 — imminent, not "planned for white-label."
Also: the multi-tenant Agency model with `agency_id` on every table must be
designed before the migration, not after.

**Required change in CLAUDE.md Stack section:**
`SQLite (dev/prod) → PostgreSQL (Phase 2.5 — imminent, prerequisite for Phase 3)`

And add a new section:

```markdown
## Multi-Tenant Architecture — MUST be designed before Phase 3

Every table requires agency_id FK. This must be built into PostgreSQL
schema from scratch — not retrofitted onto SQLite.

Key model:
class Agency(db.Model):
    id, name, slug, google_workspace_domain
    dialpad_api_key, retell_api_key
    healthsherpa_agency_id, plan_tier, is_active

All queries MUST include agency_id filter:
Customer.query.filter_by(id=id, agency_id=current_user.agency_id).first_or_404()
```

---

### 🔴 CRITICAL #6 — HealthSherpa Not Mentioned in Any File

**What the files say:**
HealthSherpa appears NOWHERE in CLAUDE.md, FOUNDERS_PORTAL_CONTEXT.md, or PRODUCT_VISION.md.

**What SESSION_UPDATE says:**
HealthSherpa is replacing MedicareCENTER as the enrollment platform.
Webhook integration is HIGH PRIORITY for Phase 3.
Agency account setup is pending (not yet done).
MCP server available for Claude Code:
`claude mcp add --transport http HealthSherpa-Medicare-Docs https://docs.medicare.healthsherpa.com/~gitbook/mcp`

**Required additions:**

CLAUDE.md — add to Stack section:
`Enrollment: HealthSherpa Medicare (replacing MedicareCENTER) — webhook integration Phase 3`

CLAUDE.md — add to Phase 3 checklist:
```
- [ ] Create Founders agency account at medicare.healthsherpa.com (Settings → Agency account conversion)
- [ ] Note captive join code (LOA agents: Mike, Betty, Anjana) and
      independent join code (AOR agents: Tim, Chris, Rebekah, Justin, Brian)
- [ ] Email medicare-integrations@healthsherpa.com with callback URL + API key
      Callback URL: https://portal.foundersinsuranceagency.com/enrollments/webhook/healthsherpa
- [ ] Add HealthSherpa MCP to Claude Code:
      claude mcp add --transport http HealthSherpa-Medicare-Docs https://docs.medicare.healthsherpa.com/~gitbook/mcp
- [ ] Store HEALTHSHERPA_API_KEY, HEALTHSHERPA_WEBHOOK_SECRET in VPS .env
```

FOUNDERS_PORTAL_CONTEXT.md Section 3 (Tech Stack):
- Replace: `MedicareCenter | Enrollment platform | All agents | Integrate via PDF OCR, don't replace`
  → `HealthSherpa Medicare | Enrollment platform | Replacing MedicareCENTER | Webhook integration Phase 3`
  → Add note: `MedicareCENTER PDF OCR still planned for legacy data; HealthSherpa webhooks for new enrollments`

FOUNDERS_PORTAL_CONTEXT.md Section 13 (MedicareCENTER Integration):
- Add paragraph: `HealthSherpa Medicare now the primary enrollment platform.
  Webhook fires on every enrollment submission — payload includes full PII for captive agents
  (LOA join code) and limited data for AOR agents (independent join code per carrier).
  external_id field = portal customer ID — bidirectional sync key.`

---

### 🟡 STALE #1 — MedicareCENTER PDF OCR Still Listed as Primary Integration

**What the files say:**
FOUNDERS_PORTAL_CONTEXT.md Section 13: Full MedicareCENTER PDF OCR integration plan
FOUNDERS_PORTAL_CONTEXT.md Section 3: `MedicareCenter | Integrate via PDF OCR, don't replace`
PRODUCT_VISION.md: `MedicareCenter PDF OCR → auto-match to customer record` listed as key feature

**Reality:**
HealthSherpa webhooks replace the need for MedicareCENTER PDF OCR for NEW enrollments.
PDF OCR may still be useful for importing historical/legacy enrollments.

**Required change:**
Reframe PDF OCR as "legacy data import only" not primary integration path.
Add note that HealthSherpa webhooks are the live integration going forward.

---

### 🟡 STALE #2 — PRODUCT_VISION.md Phase Order Doesn't Match Reality

**What PRODUCT_VISION.md says:**
- Phase 1 ✅ Core
- Phase 2 🔜 Customer Master
- Phase 3 Compliance + Reference
- Phase 4 Communication Hub
- Phase 5 Operations + Admin
- Phase 6 Analytics
- Phase 7 Mobile + Customer Portal
- Phase 8 White Label

**What FOUNDERS_PORTAL_CONTEXT.md and SESSION_UPDATE say:**
- Phase 1 ✅ Core
- Phase 2 ✅ Customer Master (COMPLETE)
- Phase 2.5 🔜 PostgreSQL migration (NEW — HARD PREREQUISITE)
- Phase 3 🔜 Communication Hub ← moved up
- Phase 4 Compliance + Operations ← combined and moved
- Phase 5 Analytics
- Phase 6 Mobile + Customer Portal
- Phase 7 White Label

**Required change:** Reorder PRODUCT_VISION.md Section 6 to match actual build order.
Communication Hub was moved to Phase 3 because it's the highest-value feature
for Founders operations before AEP. Compliance/Reference moved to Phase 4.

---

### 🟡 STALE #3 — CLAUDE.md Build Status Says Phase 3 is OpenPhone

**What CLAUDE.md says:**
`Phase 3 🔜 — OpenPhone + Calendly + Fireflies webhooks (OpenPhone account not yet set up)`

**Reality:**
Phase 3 is Communications Hub with Dialpad + Retell AI + Google Meet + HealthSherpa.
OpenPhone and Fireflies are both eliminated. Phase 2.5 must come first.

**Required change:**
```markdown
- **Phase 2.5 🔜** — PostgreSQL migration + multi-tenant agency_id (MUST DO FIRST)
- **Phase 3 ⏳** — Communications Hub (after Phase 2.5)
  Dialpad + Retell AI + Google Meet + HealthSherpa + Calendly
```

---

### 🟡 STALE #4 — Quo Still in Open Questions

**What SESSION_UPDATE Section 17 says:**
`- [ ] Does Quo trial offer SIP forwarding?`
And various Quo references remain.

**Reality:**
Dialpad was chosen over Quo. Quo trial ended. Quo is no longer being evaluated.

**Required change in SESSION_UPDATE:**
Replace any remaining Quo references with confirmed Dialpad decision.

---

### 🟡 STALE #5 — BAA Status Not Tracked in Any Project File

**What the files say:**
CLAUDE.md, FOUNDERS_PORTAL_CONTEXT.md, PRODUCT_VISION.md — none of them track
which vendors have signed BAAs.

**Reality:**
BAA status is a critical compliance requirement that should be tracked.
Current status from audit:
- Google Workspace: ❌ NOT YET SIGNED (do today — 10 min, free, Admin console)
- Dialpad: ❌ NOT YET SIGNED (sign during trial signup, in Admin Portal)
- Retell AI: ❌ NOT YET SIGNED (click-agreements.retellai.com — self-serve)
- SendGrid: ⚠️ VERIFY plan tier supports BAA
- HealthSherpa: ⚠️ VERIFY during agency account setup
- Calendly: ❌ WILL NOT SIGN — keep intake forms PHI-free
- NixiHost: ❌ WILL NOT SIGN — accepted risk for Founders internal only
- Make.com: ⚠️ VERIFY before routing PHI through scenarios

**Required addition to CLAUDE.md:**
Add a BAA Status section tracking each vendor.

---

### 🟡 STALE #6 — PRODUCT_VISION.md Still References Pharmacies as Customers

**What PRODUCT_VISION.md says:**
Several references to pharmacies as potential platform users/customers.

**What SESSION_UPDATE says:**
White-label target is Medicare agencies ONLY (1-20 agents).
Pharmacies are referral partners, not SaaS customers.
Remove pharmacy language from white-label sections.

**Required change:**
PRODUCT_VISION.md Section 4 (Target Market) — remove any pharmacy customer language.
Keep pharmacies only as the partner relationship WITHIN agencies.

---

### 🟢 MINOR #1 — Two Stray Files in Repo Root

**What exists in the repo:**
```
/tmp/founders-portal/founders-portal-main/erver {    ← truncated nginx config fragment
/tmp/founders-portal/founders-portal-main/t          ← unknown file
```
These appear to be accidentally committed file fragments (possibly a cut nginx config
and a single-character file). They have no business being in the repo root.

**Required change:**
```bash
git rm "erver {"
git rm "t"
git commit -m "Remove accidentally committed file fragments"
git push origin main
```

---

### 🟢 MINOR #2 — SKILL Files in Repo Root

**What exists:**
`SKILL Prompt.md`, `SKILL UX.md`, `SKILL WebApp.md` in the repo root.

These are your Antigravity/GSD skill files. They should either be:
1. In a `/skills/` subdirectory to keep repo root clean, OR
2. Listed in `.gitignore` if they're IDE-level files not meant for the repo

**Required change:**
```bash
mkdir skills
git mv "SKILL Prompt.md" skills/
git mv "SKILL UX.md" skills/
git mv "SKILL WebApp.md" skills/
git commit -m "Move skill files to skills/ subdirectory"
```
OR add them to `.gitignore` if they're not meant to be in the repo.

---

### 🟢 MINOR #3 — CLAUDE.md Still Says Antigravity Using Gemini

Nothing in CLAUDE.md acknowledges that Gemini sessions have contributed to
the project, which means Claude Code has no context about the Gemini-originated
decisions that have since been superseded (like the original Twilio-as-primary decision).

**Required addition to CLAUDE.md:**
```markdown
## AI Session History
This project is developed using Claude Code (primary) and Claude.ai for planning.
Some earlier decisions were made in Gemini sessions — these have been reviewed
and where conflicts existed, SESSION_UPDATE_2026-03-24.md is authoritative.
Always defer to SESSION_UPDATE_2026-03-24.md over older context in this file.
```

---

## COMPLETE FILE UPDATE CHECKLIST

### CLAUDE.md — 8 changes required
- [ ] Stack: OpenPhone → Dialpad + Retell AI
- [ ] Stack: SQLite → PostgreSQL note updated (imminent, not distant)
- [ ] Build Status: Phase 2 marked ✅ complete
- [ ] Build Status: Phase 2.5 added (PostgreSQL migration)
- [ ] Build Status: Phase 3 description updated (remove OpenPhone/Fireflies)
- [ ] Phase 3 Pre-Code Checklist: Replace OpenPhone steps with Dialpad + Retell + HealthSherpa
- [ ] Add Multi-Tenant Architecture section
- [ ] Add BAA Status section
- [ ] Add AI Session History note

### FOUNDERS_PORTAL_CONTEXT.md — 12 changes required
- [ ] Section 3: OpenPhone → Dialpad row
- [ ] Section 3: Add Retell AI row
- [ ] Section 3: Add Twilio (utility only) row
- [ ] Section 3: Fireflies → Google Meet native row
- [ ] Section 3: MedicareCENTER → HealthSherpa row
- [ ] Section 13: Add HealthSherpa webhook note
- [ ] Section 14: Communication stack updated (OpenPhone → Dialpad/Retell)
- [ ] Section 17 Phase 3 Pre-Code: OpenPhone → Dialpad + Retell + HealthSherpa
- [ ] Section 17 Phase 3 Code: Fireflies webhook → Google Meet webhook
- [ ] Section 17 Roadmap: Add Phase 2.5 between Phase 2 and 3
- [ ] Section 18 Notes: Update OpenPhone/Fireflies/RingCentral references
- [ ] Last Updated date: March 20 → March 25, 2026

### PRODUCT_VISION.md — 7 changes required
- [ ] Section 5 Add-ons: Communication Hub description (RingCentral → Dialpad)
- [ ] Section 5 Add-ons: Remove Fireflies Integration line item
- [ ] Section 6: Phase 2 marked ✅ complete
- [ ] Section 6: Phase order restructured (Communication Hub → Phase 3)
- [ ] Section 6: Phase 2.5 PostgreSQL migration added
- [ ] Section 7 APIs table: Remove RingCentral + Fireflies, add Dialpad + Retell + Google Meet + HealthSherpa
- [ ] Section 4: Remove pharmacy-as-customer language

### SESSION_UPDATE_2026-03-24.md — 1 change required
- [ ] Remove any remaining Quo references (Dialpad is confirmed)

---

## COMMAND TO GIVE CLAUDE CODE

After manually making the above changes (or asking Claude Code to make them),
give Claude Code this command to start the next session clean:

```
I've just completed a project audit. Read these files in order:
1. PROJECT_AUDIT_2026-03-25.md — what was wrong and what was fixed
2. SESSION_UPDATE_2026-03-24.md — all authoritative decisions
3. CLAUDE.md — updated project context
4. FOUNDERS_PORTAL_CONTEXT.md — updated full context

The authoritative stack for Phase 3 is:
- Phone system: Dialpad (primary) — NOT OpenPhone, NOT RingCentral, NOT Twilio
- Missed calls: Retell AI via Dialpad SIP forwarding
- Utility SMS: Twilio (edge cases only)
- Recording: Google Meet native (NOT Fireflies)
- Enrollment data: HealthSherpa webhooks
- HARD PREREQUISITE: Phase 2.5 (PostgreSQL + multi-tenant agency_id) before ANY Phase 3 code

Do NOT write any Phase 3 webhook handlers until Phase 2.5 is complete.
First task: [whatever you want to build next]
```

---

## ON STITCH MCP FOR UI

You mentioned using Stitch MCP to generate UI. A few things to flag:

1. Stitch-generated components need to follow your existing design system:
   Navy #1B2A4A, Blue #185FA5, Gold #C9A84C, 200px sidebar, system font stack.
   When prompting Stitch, always include these constraints or the UI will
   look inconsistent with existing templates.

2. Stitch output will likely use component-based HTML/CSS. Your existing
   stack is Vanilla JS + Jinja2 templates with CSS in `{% block styles %}`.
   Make sure Stitch output gets adapted to this pattern — no separate CSS
   files, no React/Vue components unless you're ready to change the stack.

3. For new Phase 3 templates (communications dashboard, activity feed,
   call log view) — prompt Stitch with your existing base.html structure
   so it generates something that extends correctly.

---

*Audit complete. Total issues found: 6 critical, 6 stale, 3 minor.*
*All critical issues involve the wrong phone system or missing new components.*
*Primary cause: Three separate AI tools (Claude.ai, Claude Code, Gemini)*
*making decisions in isolation without a single source of truth.*
*Solution going forward: SESSION_UPDATE docs are the single source of truth.*
*Update CLAUDE.md immediately after every planning session.*
