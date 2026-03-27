# Phase 3: Communications Hub - Research

**Researched:** 2026-03-26
**Domain:** Webhook integrations (Dialpad, Retell AI, Calendly, Google Meet, HealthSherpa), SMS/email delivery, multi-tenant query scoping, Flask blueprint architecture
**Confidence:** MEDIUM-HIGH (external API payload details partially LOW due to docs access issues; core patterns HIGH)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Dialpad is the primary telephony service** — webhooks for call.completed (state=hangup), call.missed (state=missed), voicemail.created (state=voicemail_uploaded)
- **Twilio is edge-case only** — for situations where Dialpad cannot deliver (e.g., programmatic SMS blasts, Retell AI SIP trunking)
- **Retell AI** handles inbound missed calls — AI triage, appointment booking mid-call via Calendly
- ROADMAP references to "Twilio as primary" are superseded by this decision
- **HMAC signature verification required on all webhook endpoints** (Dialpad signing secret, Retell AI, Calendly, HealthSherpa)
- **Do NOT add 8 new tables from ROADMAP** (CallLog, SmsMessage, etc.) — extend CustomerNote instead
- Extend CustomerNote with: `dialpad_call_id`, `twilio_msg_sid`, `retell_call_id`
- Add new note_type values: `voicemail`, `healthsherpa_enrollment`
- `UnmatchedCall` table still needed (separate from CustomerNote)
- Normalize all incoming phone numbers to E.164 before matching
- Match against `Customer.phone_primary` first, then `Customer.phone_secondary`
- If no match: log to `UnmatchedCall` — do NOT auto-create stub customers
- Agent-scoped unmatched calls (keyed by Dialpad line/agent); admin sees all
- Sidebar badge on agent dashboard shows unresolved count
- All existing queries gain `filter_by(agency_id=current_user.agency_id)`
- Add `sms_consent_at` datetime to Customer (NULL = no consent)
- SMS template approval: agents suggest, admin (AJ) approves; only approved templates visible to agents
- Calendly: match by phone first, then email; unmatched goes to same queue
- Upcoming appointments card on agent dashboard — next 5 appointments with pre-call brief
- Google Meet `meeting_summary` CustomerNote auto-created via Workspace Events API + Pub/Sub
- New secrets: DIALPAD_HMAC_SECRET, RETELL_WEBHOOK_SECRET, CALENDLY_WEBHOOK_SECRET, HEALTHSHERPA_WEBHOOK_SECRET, GOOGLE_MEET_WEBHOOK_SECRET

### Claude's Discretion
- Exact Dialpad webhook event schema and field names
- Retell AI SIP trunk configuration specifics
- HealthSherpa webhook payload structure and consent field presence
- Calendly webhook event payload structure for invitee phone/email
- Google Workspace Events API setup and subscription configuration
- Exact E.164 normalization library choice (phonenumbers Python library is standard)
- UnmatchedCall table exact columns

### Deferred Ideas (OUT OF SCOPE)
- Automated reminder sequences (day-before + 1-hour SMS/email) — Phase 5 or standalone phase
- Email campaign module — can be Phase 3.1
- SOA creation + e-signature — Phase 4+
- CustomerTask model — CONTEXT.md notes: evaluate if CustomerNote with note_type='task' suffices instead
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SC-1 | Agent sees all calls (completed + missed) with timestamp, duration, direction, AI summary on customer profile — no manual entry | Dialpad webhook state=hangup/missed payload; CustomerNote extension pattern |
| SC-2 | Agent sees full SMS thread with customer on customer profile — inbound and outbound via Dialpad | Dialpad SMS webhook payload; CustomerNote note_type=sms |
| SC-3 | After Calendly booking, pre-call brief appears on agent dashboard automatically | Calendly invitee.created webhook; UpcomingAppointment card in dashboard context |
| SC-4 | After Google Meet appointment, AI-extracted summary appears on customer profile — no manual entry | Google Workspace Events API + Pub/Sub; transcript.fileGenerated event; Meet REST API |
| SC-5 | Agent can send admin-approved CMS-compliant SMS template to consenting customer | SmsTemplate model; Twilio send API; sms_consent_at guard; SMST-01..04 |
| SC-6 | Inbound call from unknown number creates UnmatchedCall and surfaces in agent's resolution queue | UnmatchedCall model; sidebar badge via context_processor; resolution UI |
| SC-7 | Every database query scoped to agency_id — no cross-tenant data | agency_id FK on all tables; filter_by pattern; migration strategy |
</phase_requirements>

---

## Summary

Phase 3 is a webhook-heavy integration phase connecting five external services (Dialpad, Retell AI, Calendly, Google Meet via Workspace Events API, and HealthSherpa) to the existing Flask/PostgreSQL portal. The core architectural decision from CONTEXT.md is to extend the existing `CustomerNote` model rather than create a proliferation of new tables — this keeps the data model simple and reuses all existing note-rendering UI across customer profiles.

The most architecturally complex element is Google Meet integration: unlike the other providers, Google Workspace Events API delivers notifications via Google Cloud Pub/Sub, not HTTP webhooks. This means the portal needs a Pub/Sub pull subscriber (a background process or Cloud Run function), not just a Flask route. This is the highest-risk item in the phase and needs a clear architectural decision before implementation begins.

Dialpad uses JWT-signed payloads (HS256) rather than HMAC-SHA256 headers. SMS message content requires an explicit `message_content_export` API scope — this must be configured before any SMS webhook handler will receive message body text. All webhook endpoints must return 200 within 3 seconds (WEBH-03); for the Google Meet path this is inherently satisfied since Pub/Sub is asynchronous.

**Primary recommendation:** Implement webhook handlers in waves — (1) schema migrations + agency_id scoping, (2) Dialpad calls + SMS, (3) Calendly + UnmatchedCall UI, (4) HealthSherpa enrollment, (5) Google Meet Pub/Sub subscriber. This isolates the Pub/Sub complexity to the final wave.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| phonenumbers | >=8.13 | E.164 normalization and validation | Google's libphonenumber port; standard for phone normalization in Python |
| PyJWT | >=2.8 | Decode + verify Dialpad JWT-signed webhooks | Dialpad uses HS256 JWT; PyJWT is the standard Python JWT library |
| google-cloud-pubsub | >=2.21 | Pull Google Workspace Events from Pub/Sub | Required for Meet transcript delivery — not HTTP webhook |
| google-auth (already installed) | 2.27.0 | OAuth2 credentials for Meet REST API | Already in requirements.txt |
| twilio | >=8.0 | Send SMS via Twilio (edge cases + SMS blasts) | Official Twilio Python library |

### Already Installed (reuse)
| Library | Purpose |
|---------|---------|
| sendgrid==6.11.0 | Email campaigns (already present) |
| requests==2.31.0 | HTTP calls to Calendly API for invitee details lookup |
| google-api-python-client==2.118.0 | Google Meet REST API for transcript content retrieval |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hmac (stdlib) | Python 3.10 | Verify Calendly + HealthSherpa signatures | stdlib — no install needed |
| hashlib (stdlib) | Python 3.10 | Used with hmac for SHA256 | stdlib |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| phonenumbers | regex-based normalization | phonenumbers handles edge cases (extensions, international formats, validation); regex cannot |
| google-cloud-pubsub | HTTP push endpoint | Push requires publicly accessible URL per subscription; pull is simpler for single-tenant VPS |
| PyJWT | python-jose | PyJWT is simpler, maintained, correct for HS256 |

**Installation (new packages only):**
```bash
pip install phonenumbers PyJWT google-cloud-pubsub twilio
```

Add to requirements.txt:
```
phonenumbers>=8.13.0
PyJWT>=2.8.0
google-cloud-pubsub>=2.21.0
twilio>=8.0.0
```

---

## Architecture Patterns

### Recommended Project Structure
```
app/
├── comms/
│   ├── __init__.py          # comms_bp = Blueprint('comms', __name__, url_prefix='/comms')
│   ├── webhooks.py          # All inbound webhook routes
│   ├── sms.py               # Twilio SMS send functions
│   ├── templates_admin.py   # SmsTemplate CRUD for admin
│   └── resolution.py        # UnmatchedCall resolution UI routes
├── scripts/
│   └── meet_subscriber.py   # Pub/Sub pull loop for Google Meet events (run as separate process)
```

### Pattern 1: Blueprint Registration (locked by CLAUDE.md)
```python
# app/__init__.py — exact 3-line pattern
from app.comms import comms_bp
app.register_blueprint(comms_bp)
```

### Pattern 2: Dialpad JWT Webhook Verification
Dialpad signs webhook payloads as HS256 JWTs when a secret is configured. The entire POST body IS the JWT token string.

```python
# Source: https://developers.dialpad.com/reference/webhookscreate + PyJWT docs
import jwt

def verify_dialpad_webhook(request):
    """Decode and verify Dialpad JWT webhook. Returns payload dict or raises."""
    token = request.get_data(as_text=True)
    secret = current_app.config['DIALPAD_HMAC_SECRET']
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.InvalidTokenError:
        abort(403)
```

### Pattern 3: Calendly Webhook Signature Verification
Calendly uses HMAC-SHA256 with a timestamp-salted payload. Header: `Calendly-Webhook-Signature`.

```python
# Source: https://developer.calendly.com community + standard HMAC pattern
import hmac, hashlib, time

def verify_calendly_webhook(request):
    sig_header = request.headers.get('Calendly-Webhook-Signature', '')
    # Format: "t=TIMESTAMP,v1=SIGNATURE"
    parts = dict(p.split('=', 1) for p in sig_header.split(','))
    timestamp = parts.get('t', '')
    provided_sig = parts.get('v1', '')
    body = request.get_data(as_text=True)
    signing_key = current_app.config['CALENDLY_WEBHOOK_SECRET']
    to_sign = f"{timestamp}.{body}"
    computed = hmac.new(
        signing_key.encode(), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(computed, provided_sig):
        abort(403)
    # Reject stale events (> 5 minutes)
    if abs(time.time() - float(timestamp)) > 300:
        abort(403)
```

### Pattern 4: Retell AI Webhook Signature Verification
Uses `x-retell-signature` header paired with the Retell API key (not a separate secret).

```python
# Source: https://docs.retellai.com/features/webhook-overview
# Retell SDK provides verify function; manual pattern:
import hmac, hashlib

def verify_retell_webhook(request):
    provided_sig = request.headers.get('x-retell-signature', '')
    body = request.get_data()
    api_key = current_app.config['RETELL_WEBHOOK_SECRET']  # This IS the Retell API key
    computed = hmac.new(api_key.encode(), body, hashlib.sha256).digest()
    import base64
    computed_b64 = base64.b64encode(computed).decode()
    if not hmac.compare_digest(computed_b64, provided_sig):
        abort(403)
```
**Note:** Verify exact signature format against Retell SDK source — confidence LOW on base64 encoding step. Retell SDK's `verify` function should be used if available.

### Pattern 5: Webhook Idempotency (WEBH-01)
Store provider event IDs before processing to prevent duplicate notes from retries.

```python
# Pattern: PostgreSQL ON CONFLICT for idempotency
# Store in CustomerNote integration key columns (dialpad_call_id, etc.)
# Before processing, check:
existing = CustomerNote.query.filter_by(
    dialpad_call_id=payload['call_id'],
    agency_id=agency_id
).first()
if existing:
    return jsonify({"status": "duplicate"}), 200  # Acknowledge, don't process
```

### Pattern 6: E.164 Phone Normalization
```python
# Source: https://pypi.org/project/phonenumbers/
import phonenumbers

def normalize_e164(raw_phone: str, default_region: str = "US") -> str | None:
    """Parse a raw phone number and return E.164 string, or None if invalid."""
    try:
        parsed = phonenumbers.parse(raw_phone, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None
```

### Pattern 7: Customer Phone Lookup
```python
def find_customer_by_phone(phone_e164: str, agency_id: int):
    """Match a normalized E.164 number against customer records."""
    return Customer.query.filter(
        Customer.agency_id == agency_id,
        db.or_(
            Customer.phone_primary == phone_e164,
            Customer.phone_secondary == phone_e164
        )
    ).first()
```

### Pattern 8: Flask Context Processor for Sidebar Badge
```python
# In app/comms/__init__.py or app/__init__.py
@app.context_processor
def inject_unmatched_count():
    if current_user.is_authenticated:
        count = UnmatchedCall.query.filter_by(
            agency_id=current_user.agency_id,
            resolved=False
        ).count()
        return {"unmatched_call_count": count}
    return {"unmatched_call_count": 0}
```
Then in `base.html`: `{% if unmatched_call_count %}<span class="badge">{{ unmatched_call_count }}</span>{% endif %}`

### Pattern 9: Agency_id Query Scoping
Every query throughout the app must include `filter_by(agency_id=current_user.agency_id)`. The migration strategy (add nullable, backfill, then NOT NULL) was already used in Phase 2.5 for existing tables. For Phase 3 new tables, add agency_id as non-nullable from the start.

```python
# Every query — no exceptions
Customer.query.filter_by(agency_id=current_user.agency_id, id=customer_id).first_or_404()
```

### Pattern 10: Google Meet Pub/Sub Architecture
Google Workspace Events API does NOT support HTTP webhooks. It requires Google Cloud Pub/Sub as the notification endpoint.

```python
# Source: https://developers.google.com/workspace/meet/api/guides/tutorial-events-python
# Subscription creation (run once, not per request):
body = {
    'targetResource': f"//meet.googleapis.com/{space_name}",
    "eventTypes": ["google.workspace.meet.transcript.v2.fileGenerated"],
    "notificationEndpoint": {"pubsubTopic": topic_name},
}
# Pub/Sub pull subscriber (scripts/meet_subscriber.py):
from google.cloud import pubsub_v1
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(project_id, subscription_id)
streaming_pull_future = subscriber.subscribe(subscription_path, callback=process_transcript_event)
```

The `fileGenerated` payload contains minimal data: `{"transcript": {"name": "conferenceRecords/CONFERENCE_RECORD_ID/transcripts/TRANSCRIPT_ID"}}`. The portal must then call the Meet REST API to retrieve full transcript content.

### Anti-Patterns to Avoid
- **Returning non-200 on valid webhook receipts**: Always 200 immediately; process asynchronously or synchronously but quickly. WEBH-03 requires 200 within 3 seconds.
- **Missing `message_content_export` scope on Dialpad API key**: Without this scope, the `text` field is absent from SMS payloads. Must configure before writing SMS note handler.
- **Storing raw phone numbers without E.164 normalization**: Webhook phone numbers and portal-stored phones must use the same format or matching will fail silently.
- **Setting `manually_edited=True` on webhook-created CustomerNotes**: Only agent profile edits set this flag — webhook writes must never touch it.
- **Using Calendly API v1**: v1 was discontinued May 2025. Use v2 API only.
- **Missing agency_id on webhook-created records**: Every webhook-created CustomerNote, UnmatchedCall, and SmsTemplate must have agency_id set at write time.
- **Using `db.create_all()` for schema changes**: Flask-Migrate (Alembic) required for all schema changes per CLAUDE.md.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Phone number parsing + E.164 | Custom regex | `phonenumbers` library | Edge cases: extensions, international codes, invalid numbers — regex cannot handle correctly |
| JWT decode + verify | Manual base64/HMAC | `PyJWT` library | Timing attacks, algorithm confusion attacks — PyJWT handles correctly |
| Pub/Sub subscription management | Custom HTTP polling | `google-cloud-pubsub` | Pub/Sub has exponential backoff, ack/nack, dead letter queue built in |
| Transactional email | SMTP via Flask-Mail | `sendgrid` SDK (already installed) | Already installed; SendGrid handles deliverability, bounce tracking, CMS opt-out headers |
| Webhook deduplication | Time-based dedup | PostgreSQL unique constraint on event ID columns | DB unique constraint is atomic; time-based dedup has race conditions |

**Key insight:** Phone number matching is the most failure-prone element in this phase. The only safe approach is E.164 normalization at every entry point: webhook receipt, customer profile save, and CSV/BOB import. Hand-rolled normalization will fail on (800) numbers, international calls, and numbers with extensions.

---

## Common Pitfalls

### Pitfall 1: Dialpad SMS `text` Field Missing
**What goes wrong:** CustomerNote for SMS is created with empty `note_text` even though the message had content.
**Why it happens:** Dialpad withholds message body by default for privacy. The `text` field is only included when the API key has `message_content_export` scope.
**How to avoid:** Configure API key scope BEFORE writing any SMS webhook handler. Test with a real SMS to verify `text` is present in the JWT payload.
**Warning signs:** `note_text` is empty string or None on all auto-created SMS notes.

### Pitfall 2: Google Meet Pub/Sub Not a Standard Webhook
**What goes wrong:** Developer creates a Flask route expecting POST from Google, but no events ever arrive.
**Why it happens:** Google Workspace Events API uses Google Cloud Pub/Sub, not HTTP push webhooks. A Pub/Sub subscription must be created and a pull subscriber process must run.
**How to avoid:** Create a dedicated `scripts/meet_subscriber.py` that runs as a separate process (systemd service or cron). Do NOT expect a Flask route to receive these events.
**Warning signs:** No `meeting_summary` notes ever appear even after verified Google Meet calls.

### Pitfall 3: Calendly Phone Number Not in Webhook Payload
**What goes wrong:** Customer matching by phone fails for all Calendly bookings.
**Why it happens:** The `invitee.created` webhook payload does NOT directly include the phone number. Phone is in the `questions_and_answers` array if the booking form asks for it, OR requires a follow-up GET to the Calendly v2 invitee endpoint using the `invitee.uri` from the payload.
**How to avoid:** Either (a) configure Calendly event types to collect phone as a required question, then parse from `questions_and_answers`, OR (b) after receiving the webhook, make a GET to the invitee URI for full details. Fall back to email matching.
**Warning signs:** All Calendly bookings landing in the unmatched queue even for existing customers.

### Pitfall 4: Agency_id Missing on Webhook Records
**What goes wrong:** Webhook creates CustomerNote without agency_id → row violates NOT NULL constraint or creates data visible across tenants.
**Why it happens:** Webhooks don't have a `current_user` context — there's no Flask login session.
**How to avoid:** Webhooks must determine `agency_id` from the webhook target/line/agent. Use the Dialpad `target.id` to look up the associated User, then get `user.agency_id`. For Calendly, look up agent from event type owner. Store the agency's ID in config for single-tenant deployments as a fallback.
**Warning signs:** IntegrityError on webhook handler, or CustomerNotes with agency_id=NULL.

### Pitfall 5: Dialpad Webhook Secret Encoding
**What goes wrong:** JWT decode fails with `InvalidSignatureError` even with correct secret.
**Why it happens:** Dialpad webhook secret may need to be byte-encoded or the key length may not meet HS256 minimum (32 bytes per RFC 7518).
**How to avoid:** Ensure `DIALPAD_HMAC_SECRET` is at least 32 characters. Use `jwt.decode(token, secret.encode(), algorithms=["HS256"])` — pass bytes, not string.
**Warning signs:** All Dialpad webhooks returning 403 in logs.

### Pitfall 6: UnmatchedCall Without Agent Scoping
**What goes wrong:** Agent A sees Agent B's unmatched calls.
**Why it happens:** UnmatchedCall query not filtered by agent_id + agency_id.
**How to avoid:** UnmatchedCall must have both `agency_id` and `agent_id` columns. Agent view filters by both; admin view filters by agency_id only.
**Warning signs:** Agents complaining about seeing unfamiliar phone numbers in their queue.

### Pitfall 7: Phone Number Format Mismatch at Query Time
**What goes wrong:** Webhook receives `+17705551234`, Customer.phone_primary stores `(770) 555-1234` — no match found, record goes to UnmatchedCall unnecessarily.
**Why it happens:** Phone numbers stored without E.164 normalization on the customer profile.
**How to avoid:** Normalize `phone_primary` and `phone_secondary` to E.164 when saving customer profiles (customer edit route). Add a one-time migration script to normalize existing records.
**Warning signs:** High UnmatchedCall volume for known customers.

---

## Code Examples

### CustomerNote Extension (Schema Migration)
```python
# Source: models.py extension pattern — add to CustomerNote class
dialpad_call_id  = db.Column(db.String(128))  # replaces openphone_call_id usage
twilio_msg_sid   = db.Column(db.String(128))  # SMS message SID
retell_call_id   = db.Column(db.String(128))  # Retell AI call ID

# note_type values to add (in addition to existing):
# 'voicemail' — Dialpad voicemail.created
# 'healthsherpa_enrollment' — HealthSherpa submission event
```

Alembic migration template:
```python
# In a new migration file generated via: flask db migrate -m "phase3 comms schema"
def upgrade():
    with op.batch_alter_table('customer_notes', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dialpad_call_id', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('twilio_msg_sid', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('retell_call_id', sa.String(128), nullable=True))
    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sms_consent_at', sa.DateTime(), nullable=True))
```

### UnmatchedCall Model
```python
class UnmatchedCall(db.Model):
    __tablename__ = "unmatched_calls"

    id             = db.Column(db.Integer, primary_key=True)
    agency_id      = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    agent_id       = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    # NULL agent_id = could not determine agent (fallback case)

    provider       = db.Column(db.String(32), default="dialpad")  # dialpad / twilio / retell
    call_sid       = db.Column(db.String(128))  # Dialpad call_id or Twilio CallSid
    from_number    = db.Column(db.String(32))   # E.164
    to_number      = db.Column(db.String(32))   # E.164
    direction      = db.Column(db.String(16))   # inbound / outbound
    duration_seconds = db.Column(db.Integer)
    occurred_at    = db.Column(db.DateTime, nullable=False)

    resolved       = db.Column(db.Boolean, default=False, nullable=False)
    resolved_at    = db.Column(db.DateTime)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    resolved_note_id = db.Column(db.Integer, db.ForeignKey("customer_notes.id"))
    # Set when agent links to customer — creates CustomerNote and links here

    created_at     = db.Column(db.DateTime, server_default=db.func.now())
```

### SmsTemplate Model
```python
class SmsTemplate(db.Model):
    __tablename__ = "sms_templates"

    id          = db.Column(db.Integer, primary_key=True)
    agency_id   = db.Column(db.Integer, db.ForeignKey("agencies.id"), nullable=False, index=True)
    name        = db.Column(db.String(256), nullable=False)
    body        = db.Column(db.Text, nullable=False)
    status      = db.Column(db.String(32), default="pending")  # pending / approved / rejected
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)
    created_at  = db.Column(db.DateTime, server_default=db.func.now())
```

### Dialpad Call Webhook Handler (Flask route)
```python
@comms_bp.route("/webhook/dialpad", methods=["POST"])
def dialpad_webhook():
    payload = verify_dialpad_webhook(request)  # 403 on invalid
    state = payload.get("state")
    call_id = payload.get("call_id")
    agency_id = _agency_from_dialpad_target(payload.get("target", {}))

    # Idempotency check
    if CustomerNote.query.filter_by(dialpad_call_id=call_id, agency_id=agency_id).first():
        return jsonify({"status": "duplicate"}), 200

    if state in ("hangup", "missed"):
        from_num = normalize_e164(payload.get("contact", {}).get("phone_number", ""))
        customer = find_customer_by_phone(from_num, agency_id) if from_num else None

        if customer:
            note = CustomerNote(
                customer_id=customer.id,
                agency_id=agency_id,
                agent_id=_agent_id_from_target(payload.get("target", {})),
                note_type="call" if state == "hangup" else "missed_call",
                dialpad_call_id=call_id,
                duration_minutes=payload.get("duration", 0) // 60000,
                contact_method="phone",
                note_text=payload.get("recording_url") or "",
                source_url=payload.get("recording_url"),
            )
            db.session.add(note)
        else:
            _create_unmatched_call(payload, agency_id, from_num)

    elif state == "voicemail_uploaded":
        _handle_voicemail(payload, agency_id)

    db.session.commit()
    return jsonify({"status": "ok"}), 200
```

### Twilio SMS Send (for approved templates)
```python
# Source: Twilio Python library docs
from twilio.rest import Client

def send_sms_template(customer, template, agent_user):
    """Send an approved SMS template to a consenting customer."""
    if not customer.sms_consent_at:
        raise ValueError("Customer has not given SMS consent")
    client = Client(
        current_app.config['TWILIO_ACCOUNT_SID'],
        current_app.config['TWILIO_AUTH_TOKEN']
    )
    message = client.messages.create(
        body=template.body,
        from_=current_app.config['TWILIO_FROM_NUMBER'],
        to=normalize_e164(customer.phone_primary)
    )
    note = CustomerNote(
        customer_id=customer.id,
        agency_id=customer.agency_id,
        agent_id=agent_user.id,
        note_type="sms",
        twilio_msg_sid=message.sid,
        note_text=f"[Template: {template.name}] {template.body}",
        contact_method="sms",
    )
    db.session.add(note)
    db.session.commit()
    return message.sid
```

### Calendly Webhook — Pre-call Brief
```python
@comms_bp.route("/webhook/calendly", methods=["POST"])
def calendly_webhook():
    verify_calendly_webhook(request)  # 403 on invalid
    data = request.json
    event_type = data.get("event")
    if event_type != "invitee.created":
        return jsonify({"status": "ignored"}), 200

    payload = data.get("payload", {})
    invitee = payload.get("invitee", {})
    scheduled_event = payload.get("scheduled_event", {})
    event_id = invitee.get("uri", "").split("/")[-1]

    # Idempotency
    if CustomerNote.query.filter_by(calendly_event_id=event_id).first():
        return jsonify({"status": "duplicate"}), 200

    # Resolve agent from event_type owner email
    owner_email = scheduled_event.get("event_memberships", [{}])[0].get("user_email", "")
    agent = User.query.filter_by(email=owner_email).first()
    agency_id = agent.agency_id if agent else None

    # Match customer by phone (from questions_and_answers) then email
    phone = _extract_phone_from_qna(invitee.get("questions_and_answers", []))
    customer = None
    if phone and agency_id:
        customer = find_customer_by_phone(normalize_e164(phone), agency_id)
    if not customer and agency_id:
        email = invitee.get("email", "")
        customer = Customer.query.filter_by(email=email, agency_id=agency_id).first()

    start_time = scheduled_event.get("start_time")
    if customer and agent:
        note = CustomerNote(
            customer_id=customer.id,
            agency_id=agency_id,
            agent_id=agent.id,
            note_type="appointment_scheduled",
            calendly_event_id=event_id,
            note_text=f"Appointment scheduled for {start_time}",
        )
        db.session.add(note)
    else:
        _create_unmatched_calendly(payload, agency_id, agent)

    db.session.commit()
    return jsonify({"status": "ok"}), 200
```

### Agency_id Scoping — Existing Query Update Pattern
```python
# BEFORE (Phase 2 pattern — must update all occurrences):
Customer.query.filter_by(id=customer_id).first_or_404()

# AFTER (Phase 3 requirement — all queries):
Customer.query.filter_by(id=customer_id, agency_id=current_user.agency_id).first_or_404()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenPhone (was in ROADMAP) | Dialpad as primary | CONTEXT.md decision 2026-03-26 | All webhook routes use /comms/webhook/dialpad not /openphone |
| Fireflies.ai for meeting summaries | Google Meet native recording via Workspace Events | ROADMAP update 2026-03-25 | No Fireflies BAA needed; saves $40/user/mo; requires Pub/Sub setup |
| Celery/Redis for async tasks | Synchronous webhook processing + Pub/Sub pull | Phase 3 constraint (VPS RAM) | Webhook handlers must complete in <3s; Meet subscriber runs as separate process |
| Calendly API v1 | Calendly API v2 only | May 2025 | v1 discontinued; all webhook subscriptions must use v2 |
| Google Workspace Events v1beta | v1 (GA) | April 30, 2025 | v1beta decommissioned for Meet; must use v1 endpoint |

**Deprecated/outdated:**
- `openphone_call_id` column in `customer_notes`: Superseded by `dialpad_call_id` — the column can remain in schema (already exists) but new code uses `dialpad_call_id`
- `fireflies_meeting_id` in `customer_notes`: Superseded by Google Meet integration; column can remain but new code uses `source_url` pointing to Google Drive transcript

---

## Open Questions

1. **Google Meet Pub/Sub: Who runs the subscriber?**
   - What we know: Pub/Sub pull requires a running process; VPS already has Gunicorn + Nginx
   - What's unclear: Should `meet_subscriber.py` run as a systemd unit, a cron, or be integrated into Gunicorn worker lifecycle?
   - Recommendation: Systemd service is cleanest; add `meet_subscriber.service` unit file in the phase. Alternatively, use Pub/Sub HTTP push endpoint (requires publicly accessible URL per subscription) which maps to a standard Flask route — simpler if VPS is always public.

2. **Calendly phone number in invitee payload**
   - What we know: Phone is not a top-level field in `invitee.created`; it's either in `questions_and_answers` (if configured) or requires a GET to the invitee URI
   - What's unclear: Does the agency's Calendly booking form ask for phone number? If not, phone matching will always fail and email-only matching is the fallback
   - Recommendation: Admin task — configure Calendly event types to include "Phone number" as a required question. Document this in Phase 3 pre-flight checklist.

3. **HealthSherpa Medicare webhook payload details**
   - What we know: One event type — enrollment submission; includes member first/last/DOB, policy info, agent NPN; contact at medicare-integrations@healthsherpa.com
   - What's unclear: Whether phone number, email, or consent fields are present in Medicare enrollment payload (only ICHRA docs were detailed); exact security method
   - Recommendation: Request payload documentation sample from HealthSherpa contact before building the handler. Treat as LOW confidence until confirmed.

4. **CustomerTask vs CustomerNote for "open tasks" in pre-call brief**
   - What we know: CONTEXT.md deferred CustomerTask model but SC-3 requires "open tasks" in pre-call brief
   - What's unclear: Whether `CustomerNote` with `note_type='task'` + a `resolved` boolean column is sufficient, or whether a separate CustomerTask model is needed
   - Recommendation: Add a `resolved` boolean column to `CustomerNote` and use `note_type='task'` for agent-created tasks. Pre-call brief queries `CustomerNote.query.filter_by(customer_id=X, note_type='task', resolved=False)`. This avoids a new model while satisfying the SC-3 requirement.

5. **Dialpad SMS `message_content_export` scope**
   - What we know: Scope must be explicitly added to the API key; cannot receive message body without it
   - What's unclear: Whether this requires contacting Dialpad support or if it's self-serve in the developer portal
   - Recommendation: Verify in Dialpad Admin Portal > API Keys before writing SMS handler. If OAuth app required, email api@dialpad.com per documentation.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (not yet installed — Wave 0 gap) |
| Config file | `pytest.ini` — Wave 0 gap |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC-1 (WEBH-01) | Duplicate Dialpad event ID rejected without creating second note | unit | `pytest tests/test_comms_webhooks.py::test_dialpad_duplicate_idempotency -x` | Wave 0 |
| SC-1 (WEBH-02) | Invalid Dialpad JWT returns 403 | unit | `pytest tests/test_comms_webhooks.py::test_dialpad_invalid_jwt -x` | Wave 0 |
| SC-1 | Dialpad hangup event creates CustomerNote(note_type=call) | unit | `pytest tests/test_comms_webhooks.py::test_dialpad_hangup_creates_note -x` | Wave 0 |
| SC-1 | Dialpad missed event creates CustomerNote(note_type=missed_call) | unit | `pytest tests/test_comms_webhooks.py::test_dialpad_missed_creates_note -x` | Wave 0 |
| SC-2 | Dialpad SMS inbound creates CustomerNote(note_type=sms) | unit | `pytest tests/test_comms_webhooks.py::test_dialpad_sms_creates_note -x` | Wave 0 |
| SC-3 | Calendly invitee.created creates CustomerNote(note_type=appointment_scheduled) | unit | `pytest tests/test_comms_webhooks.py::test_calendly_booking_creates_note -x` | Wave 0 |
| SC-3 | Calendly unmatched booking creates UnmatchedCall record | unit | `pytest tests/test_comms_webhooks.py::test_calendly_unmatched -x` | Wave 0 |
| SC-5 | SMS send blocked when sms_consent_at is NULL | unit | `pytest tests/test_comms_sms.py::test_sms_blocked_no_consent -x` | Wave 0 |
| SC-5 | Only approved templates appear in agent send list | unit | `pytest tests/test_comms_sms.py::test_only_approved_templates -x` | Wave 0 |
| SC-6 | Unknown number creates UnmatchedCall not CustomerNote | unit | `pytest tests/test_comms_webhooks.py::test_unknown_number_unmatched -x` | Wave 0 |
| SC-7 | Customer query without agency_id returns nothing (scoping) | unit | `pytest tests/test_agency_scoping.py::test_query_cross_tenant -x` | Wave 0 |
| E.164 normalization | `normalize_e164` handles US formats + invalid input | unit | `pytest tests/test_phone_utils.py -x` | Wave 0 |
| WEBH-03 | Webhook handler completes within 3 seconds | integration | manual timing test | manual |
| SC-4 Google Meet | Pub/Sub `fileGenerated` event creates `meeting_summary` note | integration | manual (requires GCP setup) | manual |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/__init__.py` — package marker
- [ ] `tests/conftest.py` — shared fixtures (app factory, test db, sample Agency/User/Customer)
- [ ] `tests/test_comms_webhooks.py` — covers SC-1, SC-2, SC-3, SC-6, WEBH-01, WEBH-02
- [ ] `tests/test_comms_sms.py` — covers SC-5, SMST-01..04
- [ ] `tests/test_phone_utils.py` — covers E.164 normalization edge cases
- [ ] `tests/test_agency_scoping.py` — covers SC-7 cross-tenant isolation
- [ ] Framework install: `pip install pytest pytest-flask` — add to requirements.txt

---

## Sources

### Primary (HIGH confidence)
- [Dialpad Call Events docs](https://developers.dialpad.com/docs/call-events) — state names (hangup, missed, voicemail_uploaded), payload fields
- [Dialpad SMS Events docs](https://developers.dialpad.com/docs/sms-events) — SMS payload structure, message_content_export scope requirement
- [Dialpad Webhook Create reference](https://developers.dialpad.com/reference/webhookscreate) — JWT HS256 signing configuration
- [Retell AI Webhook Overview](https://docs.retellai.com/features/webhook-overview) — event types (call_started/ended/analyzed), x-retell-signature header, 10s timeout + 3 retry policy
- [Retell AI Twilio SIP docs](https://docs.retellai.com/deploy/twilio) — SIP trunk setup steps, IP whitelist 18.98.16.120/30, origination URI sip:sip.retellai.com
- [Google Meet Events tutorial (Python)](https://developers.google.com/workspace/meet/api/guides/tutorial-events-python) — Pub/Sub required, subscription body, transcript.fileGenerated event, transcript retrieval via Meet REST API
- [Google Workspace Events API (Meet events)](https://developers.google.com/workspace/events/guides/events-meet) — event types, v1beta decommission April 2025
- [phonenumbers PyPI](https://pypi.org/project/phonenumbers/) — E.164 parsing and formatting API
- [PyJWT docs](https://pyjwt.readthedocs.io/en/stable/) — HS256 decode pattern
- [Flask templating — context processors](https://flask.palletsprojects.com/en/stable/templating/) — sidebar badge injection pattern

### Secondary (MEDIUM confidence)
- [Calendly Webhook Overview (help center)](https://help.calendly.com/hc/en-us/articles/223195488-Webhooks-overview) — invitee.created event, email field present, phone via questions_and_answers or follow-up GET
- [Calendly Developer Webhooks (community)](https://community.calendly.com/api-webhook-help-61) — v1 discontinued May 2025; `Calendly-Webhook-Signature` header format: `t=TIMESTAMP,v1=SIGNATURE`
- [HealthSherpa Medicare Webhooks intro](https://docs.medicare.healthsherpa.com/webhooks/introduction) — enrollment submission event type; contact: medicare-integrations@healthsherpa.com
- [optimizesmart.com Twilio + Retell AI guide](https://optimizesmart.com/blog/using-twilio-with-retell-ai-via-sip-trunking-for-voice-ai-agents/) — verified against official Retell docs

### Tertiary (LOW confidence — flag for validation)
- Retell AI signature verification exact format (base64 vs hex) — SDK should be used to verify; manual implementation unconfirmed
- HealthSherpa Medicare webhook payload exact fields (phone, consent presence) — ICHRA docs are detailed but Medicare docs are not publicly accessible in same detail; confirm with HealthSherpa contact
- Calendly phone number field presence and exact `questions_and_answers` key name — verify against live Calendly test booking

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — phonenumbers/PyJWT/twilio are well-documented, verified via PyPI and official docs
- Dialpad webhook architecture: HIGH — official docs confirmed JWT HS256, state names, SMS scope requirement
- Retell AI webhooks: MEDIUM — event types and header confirmed; exact signature verification format LOW (use SDK)
- Calendly integration: MEDIUM — v2 required confirmed; phone field location LOW (Calendly docs rendered as CSS in fetch attempts)
- Google Meet / Pub/Sub: HIGH — official Google tutorial confirmed Pub/Sub-required architecture; fileGenerated payload structure confirmed
- HealthSherpa: LOW-MEDIUM — enrollment event confirmed; payload field details for Medicare specifically unconfirmed
- Agency_id scoping patterns: HIGH — established in Phase 2.5; same Alembic pattern

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (Dialpad/Retell/Calendly APIs are stable; Google Meet API recently went GA)
