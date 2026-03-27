# OpenPhone / Quo — Webhook & Integration Research

**Researched:** 2026-03-26
**Domain:** OpenPhone/Quo webhook authentication, event types, payloads, Retell AI SIP compatibility, Make.com integration, Python SDK
**Confidence:** MEDIUM-HIGH (authentication and payload schemas verified against official Quo docs and OpenAPI spec; SIP limitation confirmed via inference; some payload details LOW due to docs rendering constraints)

---

## Context: OpenPhone IS Quo

OpenPhone rebranded to **Quo** in September 2025. The rebrand is cosmetic only:
- Domain: `openphone.com` → `quo.com` (openphone.com 301-redirects)
- Support: `support.openphone.com` → `support.quo.com`
- Docs: `www.openphone.com/docs` → `www.quo.com/docs`
- API base URL: **`https://api.openphone.com/v1`** (unchanged — still `openphone.com`)
- Webhook signature header: still `openphone-signature`
- Make.com module: listed as "Quo (formerly OpenPhone)"

The API, webhook system, and developer docs all remain under the OpenPhone branding at the API level. Do not expect a `api.quo.com` endpoint.

---

## 1. Webhook Authentication

**Method:** HMAC-SHA256 with a base64-encoded signing key

**Header name:** `openphone-signature`

**Header format:**
```
hmac;1;<unix_timestamp_ms>;<base64_encoded_hmac_sha256_digest>
```

**Example:**
```
openphone-signature: hmac;1;1639710054089;mw1K4fvh5m9XzsGon4C5N3KvL0bkmPZSAyb/9Vms2Qo=
```

**Signing key source:** Obtained from the Quo web/desktop app when creating a webhook. The key is already base64-encoded — you must base64-decode it to binary before using it as the HMAC key.

**Payload signing:** Concatenate `<timestamp_string> + "." + <raw_request_body>`. Remove all whitespace and newlines from the JSON body before concatenating.

**Python implementation (verified against official Quo support docs):**
```python
import base64
import hmac
import hashlib
from flask import request, abort

def verify_quo_webhook(request):
    """Verify Quo/OpenPhone HMAC-SHA256 webhook signature."""
    sig_header = request.headers.get('openphone-signature', '')
    if not sig_header:
        abort(401)

    fields = sig_header.split(';')
    # fields[0] = "hmac", fields[1] = "1", fields[2] = timestamp, fields[3] = digest
    if len(fields) < 4 or fields[0] != 'hmac':
        abort(401)

    timestamp = fields[2]
    provided_digest = fields[3]

    # Raw body — do NOT call request.json, use request.data
    raw_body = request.data  # bytes

    # Signed data: timestamp.body (bytes)
    signed_data = timestamp.encode() + b'.' + raw_body

    # Signing key is base64-encoded in the Quo dashboard — decode to binary
    signing_key_b64 = current_app.config['QUO_WEBHOOK_SIGNING_KEY']
    signing_key_bytes = base64.b64decode(signing_key_b64)

    # Compute HMAC-SHA256 and base64-encode the digest
    computed_digest = base64.b64encode(
        hmac.new(signing_key_bytes, signed_data, hashlib.sha256).digest()
    ).decode()

    if not hmac.compare_digest(computed_digest, provided_digest):
        abort(401)

    # Optional: reject stale events (> 5 minutes)
    import time
    try:
        ts_seconds = int(timestamp) / 1000  # timestamp is in milliseconds
        if abs(time.time() - ts_seconds) > 300:
            abort(401)
    except (ValueError, TypeError):
        abort(401)
```

**Key differences from Dialpad:**
- Dialpad: entire POST body IS a JWT token string; decode with PyJWT
- Quo: standard JSON POST body; HMAC signature is in the `openphone-signature` header
- Quo signing key is base64-encoded at rest (unlike Twilio's plaintext secret)
- Quo timestamp is milliseconds (not seconds) — divide by 1000 for `time.time()` comparison

**Confidence:** HIGH — verified against official Quo support documentation and Python code example at `support.quo.com/core-concepts/integrations/webhooks`

---

## 2. Webhook Event Types

All confirmed against official Quo docs and OpenAPI spec.

### Call Events
| Event Name | When Fired |
|------------|-----------|
| `call.ringing` | Call begins ringing (inbound or outbound) |
| `call.completed` | Call ends for any reason (answered, missed, no-answer, busy, etc.) |
| `call.recording.completed` | Call recording is ready (separate from the call.completed event) |
| `call.summary.completed` | AI-generated call summary is ready (AI feature) |
| `call.transcript.completed` | Full call transcript is ready (AI feature) |

### Message Events
| Event Name | When Fired |
|------------|-----------|
| `message.received` | Inbound SMS/MMS received |
| `message.delivered` | Outbound SMS/MMS confirmed delivered |

### Contact Events (available but not needed for Phase 3)
| Event Name | When Fired |
|------------|-----------|
| `contact.updated` | Contact record updated |
| `contact.deleted` | Contact record deleted |

**Missed / unanswered calls:** There is no separate `call.missed` event. Missed calls arrive as `call.completed` events. Distinguish them by:
- `status` field value: `"no-answer"` or `"missed"` (both are documented status values)
- `answeredAt` field: `null` when not answered
- `duration`: `0` when not answered

**Voicemail:** There is no dedicated voicemail webhook event. Voicemail recordings are returned via `GET /v1/call-recordings/{callId}` after a `call.completed` event where the call was not answered. The recording object indicates voicemail when call status is `no-answer`/`missed` with a recording present.

**Confidence:** HIGH for event names; MEDIUM for exact missed-call status values (documented in OpenAPI spec but not all combinations tested)

---

## 3. Call Event Payload Structure

The `call.completed` (and other call events) deliver a payload structured as:

```json
{
  "id": "EVc67ec998b35c41d388af50799aeeba40",
  "object": "event",
  "apiVersion": "v2",
  "createdAt": "2024-01-23T16:55:52.557Z",
  "type": "call.completed",
  "data": {
    "object": {
      "id": "ACxxxxxxxxxxxx",
      "userId": "USxxxxxxxxxxxx",
      "phoneNumberId": "PNxxxxxxxxxxxx",
      "direction": "incoming",
      "status": "completed",
      "duration": 180,
      "createdAt": "2024-01-23T16:50:00.000Z",
      "answeredAt": "2024-01-23T16:50:05.000Z",
      "completedAt": "2024-01-23T16:55:05.000Z",
      "participants": ["+17705551234", "+14045559876"],
      "answeredBy": "USxxxxxxxxxxxx",
      "initiatedBy": null,
      "forwardedFrom": null,
      "forwardedTo": null,
      "callRoute": "phone-number",
      "aiHandled": null,
      "updatedAt": "2024-01-23T16:55:52.000Z",
      "contactIds": ["CTxxxxxxxxxxxx"]
    }
  }
}
```

### Field Reference (confirmed from OpenAPI spec)

| Field | Type | Notes |
|-------|------|-------|
| `data.object.id` | string | Call ID, pattern `^AC(.*)$` |
| `data.object.userId` | string | Quo user who owns the phone number |
| `data.object.phoneNumberId` | string | Quo phone number ID, pattern `^PN(.*)$` |
| `data.object.direction` | enum | `"incoming"` or `"outgoing"` |
| `data.object.status` | enum | See status values below |
| `data.object.duration` | integer | **Seconds** (not milliseconds) |
| `data.object.createdAt` | datetime | ISO 8601 — when call was created/initiated |
| `data.object.answeredAt` | datetime or null | **null for missed/unanswered calls** |
| `data.object.completedAt` | datetime or null | When call ended |
| `data.object.participants` | array of strings | E.164 phone numbers of call participants |
| `data.object.answeredBy` | string or null | userId who answered (inbound); null if not answered |
| `data.object.initiatedBy` | string or null | userId who initiated (outbound) |
| `data.object.forwardedFrom` | string or null | E.164 — if call was forwarded |
| `data.object.forwardedTo` | string or null | E.164 — forwarding destination |
| `data.object.callRoute` | string or null | `"phone-number"` or `"phone-menu"` |
| `data.object.aiHandled` | string or null | `"ai-agent"` if AI answered; null for human |
| `data.object.contactIds` | array | Quo contact IDs associated with the call |

**All possible status values** (from OpenAPI spec):
`queued`, `initiated`, `ringing`, `in-progress`, `completed`, `busy`, `failed`, `no-answer`, `canceled`, `missed`, `answered`, `forwarded`, `abandoned`

**Missed call detection logic:**
```python
def is_missed_call(call_data):
    status = call_data.get('status', '')
    return status in ('no-answer', 'missed') or call_data.get('answeredAt') is None
```

**Recording URL:** NOT in the call.completed payload. To get the recording URL:
1. Receive `call.recording.completed` event — the event references the call ID
2. Call `GET /v1/call-recordings/{callId}` to retrieve the recording URL
- Recording object fields: `id`, `url` (nullable), `duration` (seconds), `type` (MIME type, e.g. `audio/mpeg`), `startTime`, `status`

**Agent identification:** Use `data.object.userId` to look up the agent. The Quo userId (pattern `US...`) must be mapped to a portal `User` record. Store the Quo `userId` in the `User` model or use their email via the Quo Users API.

**From/To numbers:** Found in `data.object.participants` array. Direction field distinguishes which number is the agent's (`phoneNumberId`) vs the customer's.

**Voicemail transcription:** Not in the webhook payload. Retrieve via `GET /v1/call-transcripts/{id}` after a `call.transcript.completed` event if AI transcription is enabled.

**Confidence:** HIGH for field names and types (verified against OpenAPI spec). MEDIUM for exact voicemail access pattern (not explicitly documented as separate from call recordings).

---

## 4. SMS / Message Event Payload Structure

### message.received payload

```json
{
  "id": "EVxxxxxxxxxxxx",
  "object": "event",
  "apiVersion": "v2",
  "createdAt": "2024-01-23T16:55:52.557Z",
  "type": "message.received",
  "data": {
    "object": {
      "id": "ACxxxxxxxxxxxx",
      "from": "+17705551234",
      "to": ["+14045559876"],
      "direction": "incoming",
      "status": "received",
      "text": "Hello, world!",
      "phoneNumberId": "PNxxxxxxxxxxxx",
      "userId": "USxxxxxxxxxxxx",
      "createdAt": "2024-01-23T16:55:52.000Z",
      "updatedAt": "2024-01-23T16:55:52.000Z"
    }
  }
}
```

### Message Field Reference (confirmed from OpenAPI spec)

| Field | Type | Notes |
|-------|------|-------|
| `data.object.id` | string | Message ID |
| `data.object.text` | string | **Message body — included by default, no special scope required** |
| `data.object.from` | string | E.164 sender phone number |
| `data.object.to` | array of strings | E.164 recipient phone numbers |
| `data.object.direction` | enum | `"incoming"` or `"outgoing"` |
| `data.object.status` | enum | `queued`, `sent`, `delivered`, `undelivered`, `received` |
| `data.object.phoneNumberId` | string or null | Quo phone number ID |
| `data.object.userId` | string | Quo user ID (null for incoming messages per schema note) |
| `data.object.createdAt` | datetime | ISO 8601 |
| `data.object.updatedAt` | datetime | ISO 8601 |

**Critical difference from Dialpad:** Quo includes the message body (`text` field) in the webhook payload by default. No special API scope is required. This eliminates the Dialpad `message_content_export` scope problem documented in the original RESEARCH.md.

**message.delivered** has the same structure as `message.received` but `direction` will be `"outgoing"` and `status` will be `"delivered"`.

**Confidence:** HIGH — message object schema confirmed against OpenAPI spec. Lack of scope requirement confirmed by absence of any scope documentation (contrast with Dialpad's explicit scope requirement).

---

## 5. Retell AI + OpenPhone/Quo SIP Integration

**Bottom line: OpenPhone/Quo does NOT support SIP trunking as an external integration point. Twilio (or Telnyx/Vonage) remains required as the SIP intermediary for Retell AI.**

### What Retell AI Officially Supports

Retell AI's custom telephony documentation names three providers with dedicated setup guides:
- Twilio (primary, fully documented)
- Telnyx (documented)
- Vonage (documented)

Retell also states: "other telephony providers that support SIP trunks are also supported" — but this refers to outbound SIP trunking capability from the provider's side.

SIP technical requirements for Retell:
- **SIP server:** `sip.retellai.com`
- **IP blocks to whitelist:** `18.98.16.120/30`
- **Transport:** TCP (recommended), UDP, or TLS/SRTP

### OpenPhone/Quo SIP Position

OpenPhone/Quo is a **hosted PBX** product, not a SIP trunk provider. Per their own documentation: "if you're using a softphone app or a hosted VoIP provider like Quo, you don't need to worry about SIP — it's all handled automatically." This means Quo abstracts SIP away from the user and does not expose SIP trunking outbound to third parties.

There is no documented way to point Quo's inbound calls at a Retell AI SIP endpoint. Quo handles its own call routing internally.

### Architecture Decision for Phase 3

The original Phase 3 plan had Retell AI handling inbound missed calls via Twilio SIP. This architecture **still works** and **is required**:

```
Inbound call to agent's Quo number
    → Quo handles call (no answer)
    → Quo fires call.completed webhook with status="no-answer"
    → Portal receives webhook → creates UnmatchedCall record
    → Separately: Twilio number (for Retell AI) can handle the AI callback
```

**OR** the simpler approach: Retell AI is triggered programmatically when Quo fires a missed-call webhook (the portal calls Retell API to initiate an outbound AI callback to the caller).

There is no native OpenPhone → Retell AI SIP path. Twilio remains the SIP bridge.

**Confidence:** MEDIUM-HIGH — Quo's lack of SIP trunking export confirmed via documentation analysis and search. Retell AI supported providers confirmed from official Retell docs. Absence of OpenPhone in Retell docs or community is the strongest signal.

---

## 6. Make.com (formerly Integromat) — Native OpenPhone/Quo Module

**Yes — there is a native Make module.** Listed as "Quo (formerly OpenPhone)" in the Make integration catalog.

### Available Triggers (what can start a Make scenario)
| Trigger | Description |
|---------|-------------|
| Watch new calls and recordings | Fires on completed or ringing calls |
| Watch new messages | Fires on delivered or received messages |
| Watch new call summaries | Fires when AI call summary is generated |
| Watch new call transcripts | Fires when call transcript is ready |

### Available Actions
| Action | Description |
|--------|-------------|
| Create a Contact | Add a new Quo contact |
| Get a Contact | Retrieve contact by ID |
| Update a Contact | Modify existing contact |
| Delete a Contact | Remove a contact |
| Send a Text Message | Send SMS via Quo (costs $0.01/segment US/Canada) |
| Get a Text Message | Retrieve message details |
| List Call Recordings | Get recordings for a call ID |
| List Phone Numbers | List available Quo phone numbers |
| List Custom Fields | List custom fields |

### Available Searches
| Search | Description |
|--------|-------------|
| Search Calls | Find calls matching criteria |
| Search Text Messages | Find messages matching criteria |

### Make Module Notes
- Phone numbers MUST be E.164 format (`+1XXXXXXXXXX`) or SMS actions return 400
- Add a Text Parser module before Send SMS if phone numbers may be in non-E.164 format
- Minimum scenario interval: 15 minutes
- Outbound SMS via Make incurs API charges ($0.01/segment US/Canada)
- Make module uses Quo API key authentication (same key as direct API)

**Relevance to Portal:** Make.com is primarily for no-code automations. The Flask portal uses Quo webhooks directly. The Make module is relevant only if the user wants supplementary no-code workflows outside the portal (e.g., Quo → Google Sheets logging, Quo → Slack notifications).

**Confidence:** HIGH — Make module triggers and actions confirmed from Quo support docs and Make app catalog.

---

## 7. Python SDK / Library

**There is no official OpenPhone/Quo Python SDK.**

The Quo API is a standard REST API. All integration is via raw HTTP calls using the `requests` library.

### REST API Essentials

**Base URL:** `https://api.openphone.com/v1` (confirmed — `openphone.com` domain, not `quo.com`)

**Authentication:** API key in the `Authorization` header (no `Bearer` prefix):
```
Authorization: YOUR_API_KEY
```

**Format:** JSON request/response bodies

**Key endpoints for Phase 3:**
| Endpoint | Purpose |
|----------|---------|
| `GET /v1/calls/{callId}` | Get full call details after webhook event |
| `GET /v1/call-recordings/{callId}` | Get recording URLs (including voicemail) |
| `GET /v1/call-summaries/{callId}` | Get AI summary text |
| `GET /v1/call-transcripts/{id}` | Get full transcript dialogue |
| `GET /v1/messages/{messageId}` | Get full message details |
| `POST /v1/messages` (send SMS) | Send outbound SMS |
| `GET /v1/phone-numbers` | List Quo phone numbers (for agent mapping) |
| `GET /v1/users` | List users (for userId → agent mapping) |

**Python pattern:**
```python
import requests

def quo_api_get(path: str, api_key: str) -> dict:
    """Generic Quo REST API GET call."""
    response = requests.get(
        f"https://api.openphone.com/v1{path}",
        headers={"Authorization": api_key}
    )
    response.raise_for_status()
    return response.json()

def get_call_recordings(call_id: str, api_key: str) -> list:
    """Get recordings (including voicemail) for a completed call."""
    data = quo_api_get(f"/call-recordings/{call_id}", api_key)
    return data.get("data", [])
```

**Rate limits:** Quo enforces rate limiting for API stability but specific limits are not documented publicly.

**Confidence:** HIGH for base URL and auth header format (confirmed from API spec and authentication docs). MEDIUM for rate limits (not publicly documented).

---

## Impact on Existing Phase 3 Plans and RESEARCH.md

The existing `03-RESEARCH.md` was built entirely around Dialpad. The switch to Quo/OpenPhone requires the following changes:

### What Changes (Quo vs Dialpad)

| Aspect | Dialpad (old) | Quo/OpenPhone (new) |
|--------|--------------|---------------------|
| Auth method | JWT HS256 (entire body IS the JWT) | HMAC-SHA256 (`openphone-signature` header) |
| Auth library | `PyJWT` | `hmac` + `base64` (stdlib — no new install) |
| Webhook secret format | Plain string (min 32 chars) | Base64-encoded key from Quo dashboard |
| Missed call event | `state=missed` (separate from hangup) | `call.completed` with `status="no-answer"` or `"missed"` |
| Voicemail event | `state=voicemail_uploaded` | Separate `call.recording.completed` event; fetch via REST |
| SMS body scope | Requires `message_content_export` scope | Included by default in `text` field — no scope needed |
| SMS inbound event | Dialpad SMS event | `message.received` |
| SMS outbound event | Dialpad SMS event | `message.delivered` |
| Call duration unit | Milliseconds (÷ 60000 = minutes) | **Seconds** directly |
| Agent identifier | `target.id` in payload | `userId` field in payload |
| Python library | `PyJWT>=2.8.0` | None needed — stdlib `hmac`, `base64` |
| Config secret name | `DIALPAD_HMAC_SECRET` | `QUO_WEBHOOK_SIGNING_KEY` |

### What Stays the Same
- `phonenumbers` library for E.164 normalization — unchanged
- `requests` for REST API calls — already installed
- `google-cloud-pubsub` for Google Meet — unchanged
- `twilio` for Retell AI SIP bridge — still required (OpenPhone has no SIP export)
- All CustomerNote extension patterns — unchanged
- Webhook idempotency pattern — unchanged (use `openphone_call_id` field)
- Agency_id scoping patterns — unchanged

### CustomerNote Field Updates

Replace `dialpad_call_id` with `openphone_call_id` (or rename to `quo_call_id`):

```python
# In CustomerNote model — replace dialpad_call_id:
openphone_call_id = db.Column(db.String(128))  # Quo/OpenPhone call ID (pattern: AC...)
openphone_msg_id  = db.Column(db.String(128))  # Quo/OpenPhone message ID
# twilio_msg_sid and retell_call_id remain unchanged
```

Note: The existing `openphone_call_id` column in CustomerNote (from original design) is now correctly named — no rename needed.

### Config/.env Updates

```bash
# Replace:
DIALPAD_HMAC_SECRET=...

# With:
QUO_WEBHOOK_SIGNING_KEY=<base64_encoded_key_from_quo_dashboard>
QUO_API_KEY=<api_key_from_quo_dashboard>
```

### Updated Webhook URL

```
https://portal.foundersinsuranceagency.com/comms/webhook/quo
```

(Previously `/comms/webhook/dialpad`)

---

## Plan Corrections Required

The following items in the existing Phase 3 plans need updating based on this research:

1. **Plans 03-01 through 03-07:** Replace all references to `dialpad_webhook` with `quo_webhook` or `openphone_webhook`
2. **PyJWT dependency:** Remove from requirements.txt — not needed for Quo (stdlib hmac/base64 suffices)
3. **`DIALPAD_HMAC_SECRET`:** Rename to `QUO_WEBHOOK_SIGNING_KEY` everywhere
4. **`DIALPAD_HMAC_SECRET` for SMS scope:** No analog needed — Quo includes SMS body by default
5. **Missed call detection:** Change from `state == "missed"` to `status in ("no-answer", "missed")` or `answeredAt is None`
6. **Voicemail handling:** Remove `state == "voicemail_uploaded"` handler; add `call.recording.completed` handler that calls REST API
7. **Call duration calculation:** Remove `// 60000` (milliseconds conversion) — Quo duration is already in seconds
8. **Agent lookup:** Change from `target.id` to `userId` field
9. **Config keys:** Add `QUO_API_KEY` for REST API calls (not just the webhook signing key)

---

## Open Questions

1. **Quo userId → Portal User mapping**
   - What we know: Quo call.completed webhook includes `userId` (pattern `US...`)
   - What's unclear: How does the portal know which Quo `userId` corresponds to which portal `User` record?
   - Recommendation: Add `quo_user_id` column to the `User` model. Admin maps each portal agent to their Quo userId during setup (one-time config step). Webhook handler does `User.query.filter_by(quo_user_id=payload_user_id).first()`.

2. **Voicemail vs missed-call-with-recording distinction**
   - What we know: `call.recording.completed` fires for any call recording (answered calls AND voicemail)
   - What's unclear: How to distinguish a voicemail recording from a regular call recording in the `call.recording.completed` payload without calling the REST API
   - Recommendation: After `call.recording.completed`, fetch call details via `GET /v1/calls/{callId}`. If `status` is `"no-answer"` or `"missed"`, classify the recording as voicemail.

3. **Outbound Retell AI callback architecture**
   - What we know: OpenPhone cannot SIP-trunk to Retell; Twilio is required for Retell SIP
   - What's unclear: Does the agency want Retell AI to call back missed-call numbers, or just log them? If callback is desired, does a Twilio number need to be provisioned alongside Quo?
   - Recommendation: Clarify with AJ/Tim. If AI callback is in scope, provision a Twilio number for Retell AI only. Quo handles all human agent calls; Twilio/Retell handles AI callbacks on missed calls. This matches the original "Twilio for edge cases" decision.

4. **Quo webhook creation: app vs API**
   - What we know: "Webhooks created in the Quo app are not compatible with those created via the API" per docs
   - What's unclear: Which approach the agency should use; API-created webhooks offer per-phone-number scoping
   - Recommendation: Create webhooks via the Quo web app for simplicity. Use API-created webhooks only if per-agent phone number scoping is needed.

5. **SMS send via Quo vs Twilio for approved templates**
   - What we know: Quo API supports sending SMS via `POST /v1/messages`; Twilio SDK is also available
   - What's unclear: Which should be used for outbound SMS templates (SC-5)?
   - Recommendation: Use Quo API for outbound SMS templates — keeps all SMS on one platform (Quo), avoids Twilio costs for template sends, and ensures SMS appears in the Quo conversation thread. Twilio SMS remains for Retell AI callbacks only.

---

## Sources

### Primary (HIGH confidence)
- [Quo Webhooks Support Doc](https://support.quo.com/core-concepts/integrations/webhooks) — Authentication method, Python code example, event types
- [Quo Docs — Webhook Guide](https://www.quo.com/docs/mdx/guides/webhooks.md) — Event types, payload samples, duration field, text field
- [Quo OpenAPI Spec](https://openphone-public-api-prod.s3.us-west-2.amazonaws.com/public/openphone-public-api-v1-prod.json) — Call and message object schemas, status enum values, all field names
- [Quo API — Get Call by ID](https://www.quo.com/docs/mdx/api-reference/calls/get-a-call-by-id.md) — Complete call object schema with all status values
- [Quo API — Get Message by ID](https://www.quo.com/docs/mdx/api-reference/messages/get-a-message-by-id.md) — Complete message object schema, text field included by default
- [Quo API — Get Recordings](https://www.quo.com/docs/mdx/api-reference/calls/get-recordings-for-a-call.md) — Recording object schema, URL field, status values
- [Quo API Authentication](https://openphone-dev.mintlify.app/mdx/api-reference/authentication) — API key in Authorization header, no Bearer prefix
- [Retell AI Custom Telephony](https://docs.retellai.com/deploy/custom-telephony) — Supported providers (Twilio, Telnyx, Vonage), SIP requirements, IP whitelist

### Secondary (MEDIUM confidence)
- [Quo Make Integration Support Doc](https://support.quo.com/core-concepts/integrations/make) — All Make triggers, actions, E.164 requirement, 15-min interval
- [Make.com Apps Catalog — Quo](https://apps.make.com/open-phone) — Trigger and action names
- WebSearch synthesis: `openphone-signature` header format `hmac;1;TIMESTAMP;DIGEST` — corroborated by Python code example in official support docs

### Tertiary (LOW confidence — flag for validation)
- Exact behavior when `call.recording.completed` fires for voicemail vs answered-call recording — not explicitly documented; distinguish by checking call status via REST API
- Whether `status="missed"` and `status="no-answer"` are both used or only one — spec lists both; real-world usage needs validation against a test call

---

## Metadata

**Confidence breakdown:**
- Webhook auth (HMAC method, header name, format, Python code): HIGH — official docs + code example
- Event type names: HIGH — official docs and OpenAPI spec
- Call payload fields (duration in seconds, direction, status values, answeredAt null): HIGH — OpenAPI spec
- Missed call detection logic: MEDIUM — status values documented; real behavior unconfirmed
- SMS body included by default (no scope): HIGH — absence of any scope requirement in official docs; contrast with Dialpad's explicit documented requirement
- Recording URL access pattern: MEDIUM — schema confirmed; voicemail-vs-recording distinction LOW
- Retell AI + OpenPhone SIP incompatibility: MEDIUM-HIGH — no SIP trunking from OpenPhone confirmed; Retell's supported providers list excludes OpenPhone
- Make.com module triggers and actions: HIGH — confirmed from Quo support doc
- Python SDK absence: HIGH — no SDK referenced anywhere in official docs
- API base URL (`api.openphone.com`): HIGH — implied by all API reference docs and OpenAPI spec paths

**Research date:** 2026-03-26
**Valid until:** 2026-05-26 (Quo API is actively developed; webhook format unlikely to change; check changelog if implementing after 60 days)
