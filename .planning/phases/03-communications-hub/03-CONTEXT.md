# Phase 3: Communications Hub - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Phase Boundary

Agents see complete communication history on every customer profile — calls, SMS threads, voicemails, and meeting summaries appear automatically without manual entry. Agents can send CMS-approved SMS templates (admin-approved) and targeted email campaigns from within the portal. Inbound calls from unknown numbers surface in a per-agent resolution queue. Calendly bookings trigger a pre-call brief on the agent dashboard. All agency_id query scoping lands in this phase. Quo (formerly OpenPhone) is the primary VoIP/telephony provider; Twilio provides SIP trunking for Retell AI callbacks (Quo does not expose SIP).

</domain>

<decisions>
## Implementation Decisions

### Telephony architecture
- **Quo (formerly OpenPhone) is the primary VoIP service** — webhooks for `call.completed` (all calls; detect missed via `status in ("no-answer","missed")`), `call.recording.completed` (voicemail), `message.received`, `message.delivered`
- **Twilio is required for Retell AI SIP trunking** — Quo does not expose SIP; Retell AI only supports Twilio/Telnyx/Vonage for SIP. Twilio also handles programmatic SMS blasts.
- **Retell AI** handles missed-call AI callbacks — portal detects missed call via Quo webhook → triggers Retell AI outbound callback via Twilio SIP
- Dialpad was evaluated and rejected — did not work with Retell AI. Quo confirmed compatible.
- **Quo webhook auth: HMAC-SHA256** (stdlib `hmac`/`base64`, no PyJWT needed). Header: `openphone-signature`. Format: `hmac;1;<timestamp_ms>;<base64_digest>`. Signing key is base64-encoded in dashboard — must decode to binary before use.
- HMAC signature verification required on all webhook endpoints (Quo signing key, Retell AI, Calendly, HealthSherpa)

### Data model — extend CustomerNote, not new tables
- Do NOT add 8 new tables from ROADMAP (CallLog, SmsMessage, etc.)
- Extend CustomerNote with additional webhook ID fields: `quo_call_id` (replaces dialpad_call_id), `twilio_msg_sid`, `retell_call_id`
- Add new note_type values: `voicemail` (Quo call.recording.completed events), `healthsherpa_enrollment`
- Existing note_type values retained: `call`, `missed_call`, `sms`, `meeting_summary`, `appointment_scheduled`, `general`
- `UnmatchedCall` table still needed (separate from CustomerNote — no customer to link to yet)

### Phone number matching for webhooks
- Normalize all incoming phone numbers to E.164 format before matching
- Match against Customer.phone_primary first, then Customer.phone_secondary
- If no match found: log to UnmatchedCall table (do NOT auto-create stub customers)

### Unmatched call resolution
- Agent-scoped: each agent sees only their own unmatched calls (keyed by Quo userId → User lookup)
- Admin sees all unmatched calls across all agents
- Sidebar badge on agent dashboard shows unresolved count (e.g., "3 unresolved calls")
- Resolution UI: agent searches existing customers by name/phone to link, OR clicks "New customer" to create a lead from the number
- Once resolved, UnmatchedCall is marked resolved and a CustomerNote is created on the linked customer

### Agency_id query scoping
- All existing queries gain `filter_by(agency_id=current_user.agency_id)`
- All new webhook-created records must include agency_id on write
- This is Phase 3's responsibility — was deferred from Phase 2.5

### SMS consent model
- Add `sms_consent_at` datetime column to Customer (NULL = no consent, timestamp = consent given and when)
- Captured via toggle checkbox on customer profile edit page — sets `sms_consent_at = now()`, clears = NULL
- HealthSherpa enrollment webhook may also set sms_consent_at if enrollment implies consent
- Portal must check `sms_consent_at IS NOT NULL` before allowing agent to send any SMS

### SMS template workflow
- Agents can submit new template suggestions via the portal
- Admin reviews suggested templates in an admin panel and approves or rejects each
- Only admin-approved templates appear in the agent's "Send SMS" list
- Templates are CMS-compliant; admin (AJ) is responsible for CMS review before approval

### Pre-call brief — Calendly integration
- Calendly booking webhook fires → matches customer by phone first, then email
- If no match: logs to the unmatched queue (same queue as unmatched calls)
- Matched bookings appear in an "Upcoming Appointments" card on the agent dashboard
- Card shows next 5 appointments: customer name, time, appointment type
- Expanding an appointment shows pre-call brief: active policies (carrier + plan name + effective date), most recent CustomerNote (date + summary text), open CustomerTask items
- CustomerNote of type `appointment_scheduled` auto-created on the matched customer record

### Google Meet integration
- Google Meet recording webhook fires when transcript is ready (Workspace Events API)
- CustomerNote of type `meeting_summary` auto-created with AI-extracted summary and action items
- Matching: Meet event linked to a Calendly appointment via shared booking reference if available; fallback to agent + timestamp proximity

### Claude's Discretion
- Exact Quo webhook event schema and field names (see QUO_RESEARCH.md — confirmed against OpenPhone OpenAPI spec)
- Retell AI SIP trunk configuration specifics
- HealthSherpa webhook payload structure and consent field presence
- Calendly webhook event payload structure for invitee phone/email
- Google Workspace Events API setup and subscription configuration
- Exact E.164 normalization library choice (phonenumbers Python library is standard)
- UnmatchedCall table exact columns (call_sid, from_number, to_number, agent_id, direction, duration, resolved, resolved_at, resolved_by_id)

</decisions>

<specifics>
## Specific Ideas

- "Quo is primary VoIP, Twilio is required for Retell AI SIP" — supersedes ROADMAP and earlier Dialpad decision. Dialpad rejected after testing — incompatible with Retell AI.
- Retell AI handles the missed-call AI experience (inbound, appointment booking mid-call)
- The unmatched call sidebar badge should feel like email unread counts — agents notice it without a page visit
- Pre-call brief should show current plan + last interaction + open tasks — enough context without overwhelming
- SMS template approval flow: agents suggest, AJ approves — keeps CMS compliance responsibility with admin

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CustomerNote` (models.py:350): Already has `openphone_call_id`, `calendly_event_id`, `fireflies_meeting_id` fields and note_type enum values — extend with new fields, do not replace
- `_admin_required` decorator (customers.py): Reuse for admin-only webhook config pages and template approval views
- `Customer.phone_primary` / `Customer.phone_secondary` (models.py:275): These are the match targets for webhook phone lookup — must be normalized to E.164 at write time or query time
- `Customer.manually_edited` flag (models.py:304): Webhook writes to CustomerNote should NOT set this flag — only agent profile edits should
- Blueprint registration pattern (`__init__.py`): New `comms` blueprint registers with the exact 3-line pattern in CLAUDE.md

### Established Patterns
- `@login_required` + `current_user.is_admin` check: all admin webhook config routes follow this pattern
- Flash messages for user feedback: webhook resolution confirms flash "Call linked to [Customer Name]"
- `server_default=db.func.now()` for timestamps: use on all new columns added via Alembic
- All schema changes via Flask-Migrate (Alembic) — no `db.create_all()`, no raw DDL

### Integration Points
- `app/__init__.py`: New `comms_bp` blueprint registered here
- `app/templates/base.html`: Sidebar nav needs unmatched-call badge count (context processor or template variable)
- `app/routes.py` dashboard builder: Upcoming appointments card added to `_build_dashboard_context()` return dict
- `app/models.py`: CustomerNote extended; UnmatchedCall added; Customer gains `sms_consent_at`; new SmsTemplate model for the template library
- `.env` / `config.py`: New secrets — QUO_WEBHOOK_SIGNING_KEY (base64, decode before use), QUO_API_KEY, RETELL_WEBHOOK_SECRET, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, CALENDLY_WEBHOOK_SECRET, HEALTHSHERPA_WEBHOOK_SECRET, GOOGLE_MEET_WEBHOOK_SECRET

</code_context>

<deferred>
## Deferred Ideas

- Automated reminder sequences (day-before + 1-hour SMS/email) — Phase 5 or standalone phase; requires a scheduler
- Email campaign module (SendGrid, segmented by carrier/plan/renewal) — Phase 3 roadmap item but deprioritized if scope is too large; can be Phase 3.1
- SOA creation + e-signature — explicitly deferred (MedicareCenter handles 10-year storage); Phase 4+
- CustomerTask model (extracted from calls/SMS/meetings) — ROADMAP listed it for Phase 3, but not discussed; researcher should evaluate if it's needed for pre-call brief open tasks or if CustomerNote with note_type='task' suffices

</deferred>

---

*Phase: 03-communications-hub*
*Context gathered: 2026-03-26*
