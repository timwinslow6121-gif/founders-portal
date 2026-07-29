# Quo (OpenPhone) Full Event Capture — Design

**Date:** 2026-07-29
**Status:** Spec (from real captured payloads) — ready to plan + build as its own session
**Author:** Tim + assistant
**Grounding:** Real Quo v3 webhook payloads captured live 2026-07-29 (beta test). Full field map: scratchpad `quo_payload_map.md` (also inline below). PoC verified: webhook delivery + HMAC signature + agent resolution all work; this spec fixes what the beta exposed and adds the missing event types.

## Context — what the beta proved and exposed

The Quo webhook handler (`app/comms/webhooks.py`) was built in Phase 3 against Quo's *docs*, never live traffic, and sat dormant (no API keys on the VPS). The 2026-07-29 beta wired the keys + mapped Tim's `quo_user_id` and confirmed:

- ✅ Webhook delivery + HMAC signature verification work (real Quo 200s).
- ✅ Agent attribution via Quo user ID → portal user works.
- ❌ **Customer phone matching is broken for the entire book** — all **4,974** customer phones are stored non-E.164 (`980-406-7244`); the matcher normalizes the *incoming* number to E.164 (`+19804067244`) and compares against the raw stored string → never matches. Every call/SMS falls to Unmatched.
- ❌ **Field mappings are wrong** — the code reads a `participants` array (doesn't exist), `userId` for the agent on messages (that's the workspace owner; the sender is `createdBy`), `text` for SMS body (it's `body`), and makes a **separate API call** to fetch the recording URL (it's already in the payload at `media[0].url`).
- ➕ **Transcript + summary event types are not handled at all** (`call.transcript.completed`, `call.summary.completed`) — Tim wants them; Quo delivers them; the webhook is already subscribed.

## The Quo v3 payload model (from real captures)

Envelope: `payload["type"]`, object at `payload["data"]["object"]`. A single call produces **multiple events over ~seconds, all sharing one `callId` (`AC...`)**:
`call.completed` (base) → `call.recording.completed` (adds `media[].url`) → `call.transcript.completed` (adds `dialogue`) → `call.summary.completed` (adds `summary`+`nextSteps`). Transcript/summary carry **no phone/agent** — they enrich the existing call record by `callId`.

**message.received / message.delivered** (`object.object="message"`): `id`, `from`, `to`, `direction`, **`body`** (the text), **`createdBy`** (= the agent who sent), `conversationId`. `userId` here = workspace owner, NOT the agent.

**call.completed / call.recording.completed** (`object.object="call"`): `id`(=callId), `from`, `to`, `direction`, `status`, `answeredAt` (null ⇒ missed/voicemail), `answeredBy`, `voicemail`, **`media:[{url,type,duration}]`** (recording URL — present on recording event, `[]` on base), **`userId`** (= the agent, for calls), `conversationId`.

**call.transcript.completed** (`object.object="callTranscript"`): `callId`, **`dialogue:[{identifier(E.164 phone),content,userId,start,end}]`**, `duration`; `deepLink` sits at `data.deepLink`. Customer's E.164 appears as `identifier` in dialogue turns (fallback match source).

**call.summary.completed** (`object.object="callSummary"`): `callId`, **`summary:[str,...]`** (bullets), **`nextSteps:[str,...]`**; `deepLink` at `data.deepLink`.

**Direction → who is the customer:** customer phone = `from` if `direction=="incoming"`, `to` if `"outgoing"`.
**Agent field by event:** calls use `userId`; messages use `createdBy`.

## What this builds

### Section 1 — Correct field mappings (fix the existing handlers)
Rewrite the three existing Quo handlers to read the real v3 fields:
- **Customer phone** from `from`/`to` by `direction` (drop the nonexistent `participants` walk).
- **Agent** from `userId` on calls, `createdBy` on messages (via `User.quo_user_id`).
- **SMS body** from `body` (not `text`).
- **Recording URL** from `media[0].url` in the payload — **delete the separate `api.openphone.com/v1/call-recordings/{id}` fetch** (wrong host + unnecessary; the URL is in-band). Store in `CustomerNote.source_url`.
- **Missed** = `answeredAt is None`.

### Section 2 — Phone matching that actually works
`find_customer_by_phone` (in `app/comms/utils.py`) must match regardless of stored format. Compare on **last-10-digits** (US) of a normalized form on BOTH sides: normalize the incoming E.164 to its 10-digit national number, and match against customers whose stored phone, stripped of non-digits and leading `1`, ends in those 10 digits. Cover `phone_primary` and `phone_secondary`. This fixes matching for all 4,974 existing records without a data migration. (A separate optional backfill to normalize stored phones to E.164 is out of scope — matching-time normalization is enough and safer.)

### Section 3 — Transcript + summary handlers (new event types)
Add handlers for `call.transcript.completed` and `call.summary.completed`. Both correlate to the existing call by **`callId`**:
- Find the `CustomerNote` with `quo_call_id == callId` (the call.completed created it). If found, **enrich it**: flatten `dialogue` into readable transcript text (label agent turns where `userId` is non-null as the agent, other turns as the customer), store transcript + `deepLink`; store `summary` bullets + `nextSteps`.
- If the call was **unmatched** (no CustomerNote, only an `UnmatchedCall`), enrich the `UnmatchedCall` instead so nothing is lost before the lead is resolved.
- Idempotent: re-delivery of the same transcript/summary must not duplicate.

### Section 4 — Schema additions (migration 039)
`CustomerNote` already has `source_url`, `quo_call_id`, `twilio_msg_sid`, `resolved`. Add:
- `transcript` (Text) — flattened dialogue.
- `summary` (Text) — summary bullets + nextSteps (joined).
- `deep_link` (String 512) — Quo inbox link.

`UnmatchedCall` already has a full resolution model (`resolved`, `resolved_by`, `resolved_note_id`). Add the same capture columns so a lead's event data survives until resolved:
- `body` (Text) — SMS body or note.
- `transcript` (Text), `summary` (Text), `deep_link` (String 512), `recording_url` (String 512).
- `event_type` (String 32) — which Quo event created/enriched it.

(One migration, additive, nullable columns — no backfill.)

### Section 5 — Unmatched queue + resolve (the lead path — Lisa Fair)
When no customer matches (a lead like Lisa Fair), capture the FULL event into `UnmatchedCall` (number, direction, agent, body/transcript/summary/recording/deep_link). The existing `/comms/resolution` screen (`app/comms/resolution.py`) already lists unmatched calls and has a resolution model; extend it to:
- Show the captured body/summary preview per row.
- **Resolve action:** "Link to existing customer" (search + attach → creates the `CustomerNote` from the stored data, sets `resolved_note_id`) OR "Create lead/customer from this number" (make a minimal customer record, then link). Reuse existing customer-creation patterns; do NOT blind-auto-create (the portal has fought stub-sprawl — resolution is agent-driven).

### Section 6 — Testing & safety
- Unit tests per event type using the **real captured payloads** as fixtures (call.completed, call.recording.completed, call.transcript.completed, call.summary.completed, message.received, message.delivered).
- Phone-match test: incoming `+19804067244` matches a customer stored `980-406-7244`; the whole-book format (`704-273-7052`, `6316204081`) matches.
- Agent-attribution test: call uses `userId`, message uses `createdBy` → correct agent; owner `userId` on a message does NOT mis-attribute.
- Correlation test: transcript/summary enrich the same call note by `callId`; unmatched call's transcript/summary land on the `UnmatchedCall`.
- No-match test: unknown number → `UnmatchedCall` with full body/transcript captured; resolve → `CustomerNote` created + linked.
- Idempotency: re-delivered events don't duplicate.
- The existing 16 comms tests must stay green (rewrite their fixtures to the real v3 shape).
- HMAC signature path unchanged (works in prod). Keep always-200 responses.

## Files
- Modify: `app/comms/webhooks.py` (rewrite the 3 Quo handlers + add 2 new event handlers + correlation-by-callId).
- Modify: `app/comms/utils.py` (`find_customer_by_phone` → last-10-digit match).
- Modify: `app/models.py` (CustomerNote + UnmatchedCall columns) + migration 039.
- Modify: `app/comms/resolution.py` + its template (show captured data + link/create-lead resolve).
- Modify: `tests/test_comms_webhooks.py` (real-payload fixtures + new cases).

## Out of scope (note, don't build)
- **Outbound calling from the portal** (click-to-dial) — separate, larger.
- **Backfilling stored customer phones to E.164** — matching-time normalization makes it unnecessary; can be a later cleanup.
- **Retell AI / HealthSherpa** handlers — untouched this pass.
- **Rotating the beta Quo keys** — operational task for Tim (the keys passed through chat during the beta; rotate in the Quo dashboard).

## Deploy notes
Migration 039 (additive). Keys already in VPS `.env`. Standard deploy + restart. The webhook is already live and subscribed to all event types, so the moment this deploys, real traffic starts capturing correctly.
