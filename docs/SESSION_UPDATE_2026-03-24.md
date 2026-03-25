# Founders Portal — Session Update (MERGED)
## Session dates: March 23–24, 2026
## Sources: Claude.ai + Gemini planning sessions with Timothy Winslow

This document is the authoritative session update combining all decisions from both
sessions on March 23–24. Feed this to Claude Code alongside FOUNDERS_PORTAL_CONTEXT.md
and PRODUCT_VISION.md. Supersedes SESSION_UPDATE_2026-03-23.md entirely.

---

## ✅ ALL CONFLICTS RESOLVED — March 24, 2026

| # | Topic | Decision | Notes |
|---|---|---|---|
| 1 | AI Voice Engine | **Retell AI** | Better reliability per Reddit; pay for quality over Vapi's dev flexibility |
| 2 | Telephony | **Twilio** | Both sessions aligned; confirmed final |
| 3 | PostgreSQL migration | **Not yet started — must be added as explicit phase** | Currently SQLite; multi-tenant agency_id architecture must be built into PostgreSQL from scratch, not retrofitted |
| 4 | White-label target | **Medicare agencies only** | Pharmacies are referral partners, not SaaS customers. Remove pharmacy language from PRODUCT_VISION.md |
| 5 | Automation platform | **Make.com** | n8n not viable on 1GB VPS; Make.com already in stack and working |

---

## 1. FINAL Telephony Decision: Twilio

**Decision:** Twilio replaces RingCentral as agency telephony backbone.
Quo trial (started March 23) and Dialpad trial (started March 24) continue
for evaluation but Twilio is the intended production platform.

**Why Twilio wins:**
- Raw API access — no walled gardens, no platform restrictions
- Native SIP trunking partner for Retell AI and Vapi
- Pay-as-you-go — near-zero cost in off-season, scales for AEP
- Programmatic SMS routing without per-segment gotchas
- Automatic 100% call recording (CMS compliance requirement)
- ~60% cost reduction vs RingCentral at equivalent volume
- Every webhook, every call event, every SMS — fully programmable
- One Twilio account serves all agents (no per-seat licensing)

**Migration plan:**
- Port main Founders agency number to Twilio
- Provision fresh local numbers for 4-5 pilot agents (~$1.15/number/mo)
- Store `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` in VPS .env
- Webhook URL: `https://portal.foundersinsuranceagency.com/comms/webhook/twilio`

**Cost estimate — pending RingCentral records pull:**
- Voice calls: ~$0.0085/min inbound, ~$0.013/min outbound
- SMS: ~$0.0079/message
- Phone numbers: ~$1.15/number/month
- Full cost model to be built once RingCentral usage data is retrieved

**Action item:** Pull RingCentral call/SMS volume data to build accurate
AEP vs off-season cost comparison before canceling RingCentral.

---

## 2. FINAL AI Voice Engine Decision: Vapi vs Retell (UNRESOLVED — see Conflict 1)

**Architecture is identical regardless of which is chosen:**

```
Client calls Twilio number
↓
Twilio routes to AI Voice Engine (Vapi or Retell) via SIP
↓
AI Voice Engine answers, conducts conversation:
  - Triage: appointment or message?
  - If appointment: Charlotte or Kannapolis?
  - Hits Make.com mid-call → Calendly API → checks availability
  - Books appointment verbally in real time
  - Works on ANY phone — landline included
  - Transfers to human agent if needed
↓
Post-call webhook fires to Founders Portal
↓
Make.com processes:
  - Phone resolution chain
  - Customer match or new lead creation
  - CallLog created
  - Tasks extracted
  - Pre-call brief generated
↓
Agent dashboard updated — zero manual entry
```

**Vapi specifics (Gemini recommendation):**
- Developer-first, API-driven, highly customizable
- Deep Make.com integration — can fire webhooks mid-call
- Pay-as-you-go pricing
- Best for teams comfortable with API configuration

**Retell specifics (Claude recommendation):**
- Purpose-built for appointment booking flows
- Healthcare/insurance vertical track record
- $0.07/min pay-as-you-go, no platform fee
- HIPAA compliant, SOC2 Type II
- ~600-800ms latency — natural conversation flow
- G2 Best Agentic AI Software 2026

**Cost estimate for AEP (either platform):**
- Estimated 200 AI-handled missed calls × 3 min avg = 600 minutes
- At $0.07-0.08/min = ~$42-48 for all of AEP
- Off-season: near zero

**ElevenLabs voice layer (optional):**
- Both Vapi and Retell support ElevenLabs voices
- Recommended for senior demographic — more natural, less robotic
- $5-22/mo depending on usage tier
- Worth adding once base flow is working

---

## 3. Communication Stack — Updated for Twilio

| Channel | Tool | Direction | Cost |
|---|---|---|---|
| Phone calls (human) | Twilio | Both | ~$0.01/min |
| Phone calls (AI) | Twilio → Vapi/Retell | Inbound missed | ~$0.07-0.08/min AI |
| SMS (conversational) | Twilio | Both | ~$0.008/msg |
| SMS (appointment reminders) | Calendly native | Outbound | Free (native) |
| SMS (automated short) | Twilio programmatic | Outbound | ~$0.008/msg |
| Email (transactional/campaigns) | SendGrid | Outbound | Existing |
| Email (pre-call ANOC summary) | Make.com → SendGrid | Outbound | Minimal |
| Appointments | Calendly | Inbound | Existing |
| In-person recordings | Google Meet (unique per appt) | Agent-initiated | $0 (Workspace BAA) |
| Remote/phone recordings | Dialpad native | Both | Subscription |
| Post-appt summary email | Make.com → SendGrid | Outbound | Minimal |
| Enrollment data | HealthSherpa webhooks | Inbound | Free |

**Key insight:** SMS is for short pokes only. ANOC summaries go via email.
Calendly handles appointment reminders natively.

---

## 4. Backend Infrastructure — VPS Stability Mandates

**Host:** NixiHost Unmanaged KVM VPS
**Cost:** $5/month
**Specs:** 1GB RAM, 30GB SSD, 2 vCPU

**CRITICAL — These must be implemented before AEP webhook traffic:**

**1. Swap file (2GB)**
```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```
Required to handle webhook traffic spikes without OOM crashes.

**2. Gunicorn threading (not multi-worker)**
```bash
gunicorn --workers 2 --threads 4 --worker-class gthread app:app
```
Do NOT use multiple forked workers — each worker duplicates memory.
Threading shares memory within workers, keeping RAM usage manageable.

**3. No heavy Pandas memory loading**
- Never load full BOB CSV into memory at once
- Use chunking for any CSV processing: `pd.read_csv(..., chunksize=1000)`
- Webhook handlers must be lightweight — parse JSON, write to DB, return 200 fast

**4. PDF OCR abandoned**
Per Gemini session: `pdfplumber` PDF OCR scraping for MedicareCENTER
applications is abandoned. Too memory-intensive, too unreliable.
HealthSherpa webhooks replace this entirely.

**5. Database queries**
- Always use indexed columns for lookups (phone numbers, MBI, agent_id)
- Avoid N+1 query patterns — use SQLAlchemy eager loading where appropriate
- Paginate all list views — never load unbounded result sets

---

## 5. Multi-Tenant SaaS Architecture — Agency Model

**Decision:** Build multi-tenant from Day 1, not retrofitted later.

**New master table:**
```python
class Agency(db.Model):
    id
    name                    # "Founders Insurance Agency"
    slug                    # "founders" — used in URLs
    google_workspace_domain # "foundersinsuranceagency.com"
    twilio_account_sid      # per-agency Twilio subaccount (future)
    healthsherpa_agency_id  # for webhook routing
    plan_tier               # 'solo' / 'small' / 'agency' / 'enterprise'
    is_active
    created_at
```

**Every subsequent table gets agency_id:**
```python
# Required on ALL tables:
agency_id = db.Column(db.Integer, db.ForeignKey('agency.id'), nullable=False)

# Tables requiring this:
# User, Customer, Policy, Household, CallLog, SmsMessage,
# CustomerTask, CustomerNote, AgentLocation, Pharmacy,
# CommissionStatement, AgentCarrierContract, ImportBatch
```

**All Flask routes scoped to agency_id:**
```python
# Every query pattern:
Customer.query.filter_by(agency_id=current_user.agency_id, ...)

# Never:
Customer.query.filter_by(...)  # ← missing agency_id = data leak risk
```

**Google OAuth maps to agency via domain:**
```python
# On login callback:
email_domain = user_email.split('@')[1]
agency = Agency.query.filter_by(
    google_workspace_domain=email_domain
).first()
# If no agency found → reject login
```

**Why this matters:**
- Data isolation between agency tenants is absolute
- Founders data never visible to future Agency XYZ
- HIPAA-friendly architecture from the start
- Required for white-label SaaS launch

---

## 6. HealthSherpa Integration — Full Detail

**Status:** Webhook launched February 26, 2026. Agency account setup required.

**Setup:**
Email medicare-integrations@healthsherpa.com with:
- Callback URL: `https://portal.foundersinsuranceagency.com/enrollments/webhook/healthsherpa`
- API key

**Agency routing strategy (CRITICAL):**
All agents — including 1099 contractors — must use the **Captive Join Code**
when connecting to the Founders Agency portal on HealthSherpa.

Why this matters:
- Captive agents → HealthSherpa sends **Full Payload** (unredacted PII,
  Medicare numbers, DOB) to the Flask CRM on every application submission
- Non-captive agents → HealthSherpa sends redacted/partial data only
- Without captive join code, webhook data is incomplete and unusable

**Outside business handling:**
Non-Founders business (e.g., Physicians Mutual) handled outside CRM for now.
Keeps data flow clean and simple. Revisit in Phase 5.

**Recent HealthSherpa features (from product update log):**
- Spouse linking (Feb 6, 2026) — link contacts as spouses, one-click household view
- Secondary phone support (Jan 28, 2026) — add secondary phone with type spec
- Public intake SMS delivery (Feb 23, 2026) — existing clients get Personal Intake
  link via SMS even without email on file
- Import from HealthSherpa ACA (Feb 9, 2026) — import turning-65 clients from ACA

**HealthSherpa roadmap (coming soon — HIGH VALUE):**
- **Call recording + dialer** — record calls, save to contact profiles for 10 years
  (CMS compliance solved natively)
- **BEQ/MARx API integration** — pulls Part A/B effective dates, current Medicare
  plan, Medicaid level from CMS database for any client. MASSIVE for new lead intake.
- **Client self-enrollment PURL** — client enrolls via link with agent NPN attached.
  Passive enrollment from retiree.report content.
- **Multiple admins for agency accounts**
- **Compare vs current plan**
- **Robust reporting views**

**Webhook endpoint to build:**
```python
# app/enrollments.py (new blueprint)
POST /enrollments/webhook/healthsherpa
  → Verify HMAC signature
  → Confirm agency_id from HealthSherpa agency identifier
  → Parse full payload (name, DOB, address, carrier, plan, NPN, effective date)
  → Run customer match (name + DOB + address fuzzy match, scoped to agency_id)
  → Upsert CustomerAorHistory
  → Update Customer.deal_stage = 'enrolled'
  → Create CustomerTask: "Confirm enrollment with carrier"
  → Log to audit_logs
  → Return 200 OK
```

**Pre-switch checklist:**
- [ ] Verify carriers: UHC, Humana, Aetna, BCBS NC, Devoted, Healthspring
- [ ] Confirm all agents can create/join HealthSherpa accounts under Founders
- [ ] FMO has no contractual requirement for MedicareCENTER
- [ ] Plan comparison quality equivalent for agent workflow
- [ ] Compliance differences (if any) between platforms
- [ ] Captive join code obtained and distributed to all agents

---

## 7. Claude API — Cost and Architecture

**Critical distinction:** Claude.ai subscription ≠ Claude API. Completely separate.

**Setup:**
- One Anthropic API account for Founders Insurance Agency
- One API key stored in VPS .env as `ANTHROPIC_API_KEY`
- All agent automations bill to this one account invisibly
- No per-agent cost, no agent awareness required

**Current pricing (verified March 2026):**
- Haiku 4.5: $1/MTok input, $5/MTok output — default for call processing
- Sonnet 4.6: $3/MTok input, $15/MTok output — escalate only if needed
- New accounts: $5 free credits, no credit card required

**AEP cost estimate:**
- 4 agents × 15 appointments/day × 30 days = 1,800 calls
- ~4,000 tokens input + 300 tokens output per call at Haiku pricing
- **Total AEP cost: ~$10**
- Even at Sonnet pricing: ~$30 — negligible

**When to use Claude API:**
- Structured JSON extraction from transcripts for CRM field mapping
- Complex multi-step reasoning from conversation content
- Default: use Vapi/Retell native summaries first, only escalate to Claude API
  when structured data output is needed

---

## 8. Unified Communications Dashboard — Architecture

**Core principle:** Build once. Google OAuth identifies agent on login.
All queries scoped to `agent_id` + `agency_id`. Dashboard shows their data only.

**Agent dashboard panels:**
```
┌─────────────────────────────────┐
│  TODAY'S ACTIVITY FEED          │
│  Chronological: calls, SMS,     │
│  emails, voicemails, appts      │
├─────────────────────────────────┤
│  OPEN TASKS                     │
│  Extracted from interactions,   │
│  sorted by due date             │
├─────────────────────────────────┤
│  UPCOMING APPOINTMENTS          │
│  Next 48hrs from Calendly,      │
│  linked to customer records     │
└─────────────────────────────────┘
```

**Full inbound call data flow:**
```
Client calls Twilio number
→ If agent available: ring agent device
→ If agent unavailable: route to Vapi/Retell AI

[AI path]
→ AI conducts conversation
→ Books appointment OR takes message
→ Post-call webhook → Make.com → portal

[Human path]
→ Agent answers
→ Call recorded by Twilio (100% recording)
→ Transcript generated
→ Post-call webhook → portal

Both paths converge:
→ Phone resolution chain runs
→ Customer matched or new lead created
→ CallLog stored on customer record
→ Tasks extracted and created
→ Agent dashboard updated
→ Pre-call brief ready for next interaction
```

**Pre-call brief surfaces automatically:**
- Customer's current plan (from BOB / HealthSherpa)
- Last interaction summary
- Open tasks
- Household members and their plans
- Calendly intake form responses
- ANOC change highlights if AEP season

---

## 9. New Database Models Required

### Agency (NEW — multi-tenant root)
```python
class Agency(db.Model):
    id, name, slug, google_workspace_domain
    twilio_account_sid, healthsherpa_agency_id
    plan_tier, is_active, created_at
```

### Household (NEW)
```python
class Household(db.Model):
    id, agency_id               # FK to Agency
    name                        # "Johnson Household"
    home_phone                  # shared landline
    address1, city, state, zip_code
    notes, created_at, updated_at
```

### CustomerPhone (NEW — replaces simple phone fields)
```python
class CustomerPhone(db.Model):
    id, agency_id, customer_id
    phone_number                # E.164 format
    label                       # 'primary','secondary','cell','work','shared'
    is_verified, learned_from   # 'intake','call','agent_manual','bob_import'
    first_seen_at, last_used_at, notes
```

### CallLog (NEW)
```python
class CallLog(db.Model):
    id, agency_id, customer_id  # customer_id nullable if unresolved
    agent_id, household_id
    twilio_call_sid             # Twilio's call identifier
    vapi_call_id                # Vapi/Retell call identifier
    direction                   # 'inbound' / 'outbound'
    from_number, to_number
    duration_seconds
    recording_url               # Twilio recording URL
    transcript_url
    ai_summary                  # Vapi/Retell native summary
    ai_action_items             # JSON array
    ai_handled                  # boolean — was this an AI call?
    resolution_status           # 'auto_resolved','agent_confirmed','unmatched','ambiguous'
    resolution_note
    created_at
```

### SmsMessage (NEW)
```python
class SmsMessage(db.Model):
    id, agency_id, customer_id  # nullable
    agent_id, twilio_message_sid
    direction, from_number, to_number
    body, created_at
```

### CustomerTask (NEW)
```python
class CustomerTask(db.Model):
    id, agency_id, customer_id, agent_id
    title, description, due_date
    priority                    # 'high','medium','low'
    status                      # 'open','in_progress','done'
    source                      # 'call','sms','email','manual','fireflies','healthsherpa'
    source_id                   # FK to CallLog, SmsMessage, etc.
    created_at, completed_at
```

### UnmatchedCall (NEW)
```python
class UnmatchedCall(db.Model):
    id, agency_id, call_log_id
    from_number, ai_detected_name
    ai_summary, agent_id
    status                      # 'pending','resolved','dismissed'
    resolved_to_customer_id
    resolution_action           # 'matched_existing','created_new_lead','merged','dismissed'
    created_at, resolved_at
```

### AgentLocation (NEW)
```python
class AgentLocation(db.Model):
    id, agency_id, agent_id
    location_name               # "Charlotte - South Boulevard"
    pharmacy_name               # "Cannon Pharmacy"
    address1, city, state, zip
    calendly_event_type_url     # location-specific booking page
    days_available              # JSON: ["tuesday","wednesday","thursday","friday"]
    is_active
    notes
```

**Existing model changes:**
- ALL existing models: add `agency_id` FK (non-nullable)
- `Customer`: add `household_id` FK, add index on all phone fields
- `User`: add `twilio_phone_number` (E.164), `vapi_agent_id`

---

## 10. Phone Number Resolution Chain

Every inbound Twilio webhook runs this chain:

```
Step 1: Exact match on CustomerPhone table (scoped to agency_id)
  → High confidence → auto-resolve → attach to customer
  → resolution_status = 'auto_resolved'

Step 2: Match on Household.home_phone
  → Ambiguous → flag for agent confirmation
  → Screen pop: show household members as tap targets
  → resolution_status = 'agent_confirmed' after tap

Step 3: Match on CustomerContact.phone
  → POC/family member match
  → Pre-populate with associated customer
  → Flag: "called by [contact] on behalf of [customer]"

Step 4: No match
  → Create UnmatchedCall record
  → Extract name from AI summary if available
  → Surface in agent's Unmatched Call queue
  → Agent: create new lead / match existing / merge / dismiss
```

**Number learning:**
When agent resolves unknown number → add to CustomerPhone with
`learned_from = 'call'`. System gets smarter every call.

**Calendly booking fuzzy match:**
```
Priority:
1. Exact email → high confidence → auto-link
2. Exact phone → high confidence → auto-link
3. Normalized name + DOB → medium confidence → auto-link with flag
4. Normalized name + zip → low confidence → queue for review
5. No match → create new lead → flag for duplicate check
```
Name normalization handles: Bob/Robert, Tim/Timothy, nickname variations.

---

## 11. Medicare-Specific Edge Cases

**Shared landlines (non-household):**
- Multiple unrelated customers sharing one number (assisted living, group home)
- Model: `CustomerPhone` with `label = 'shared'`
- Resolution: always requires agent confirmation tap, never auto-resolves

**Multi-person household (e.g., Cynthia/Georgia/Betty on same line):**
- Three customers, one landline, rotating callers
- Household model handles grouping
- Screen pop shows all household members for one-tap selection

**Phone number churn:**
- Senior gets new number, calls from unknown number
- Old number still in system
- Resolution: UnmatchedCall queue → agent matches → old marked inactive

**Spouse calling on behalf:**
- Bob calls from Betty's cell about Betty's plan
- CustomerContact model: Bob is contact on Betty's record
- Call logged on Betty's record, flagged "called by Bob"

**POC is not the patient:**
- Daughter manages mom's Medicare entirely
- CustomerContact with `is_primary_contact = True` on mom's record
- Daughter's number resolves to mom's record

**Same person, multiple records:**
- Created by different agents, different phones
- Merge workflow preserves all history from both records
- `customer_duplicates.html` already exists — complete the backend

---

## 12. Multi-Location Scheduling

**Tim's locations:**
- Charlotte / South Boulevard (Cannon Pharmacy): Tue/Wed/Thu/Fri
- Kannapolis (Cannon Pharmacy): Mon/Sat
- South Park / Morrowcroft (Cannon Pharmacy): no dedicated days, 15-20 min from SB

**AI call flow:**
```
Step 1: "Schedule appointment or leave a message?"
  → Message: take it, done. No location question.

Step 2: "Charlotte or Kannapolis area?"
  → Routes to correct Calendly event type
  → Offers only days available for that location

Step 3 (optional, post-booking):
  → Portal checks address against chosen location
  → If mismatch: send gentle confirmation with both location options noted
  → Build real-time mid-call verification later
```

**Rule:** One verification question maximum. Always defer to caller's stated
preference. Harold knows where he wants to go.

---

## 13. Full Inbound AI Call Architecture

```
┌─────────────────────────────────────────────┐
│           TWILIO (Telephony)                │
│  Phone numbers, call routing, recording     │
│  ~$0.01/min + $1.15/number/mo               │
└──────────────┬──────────────────────────────┘
               │ SIP forward when unavailable
               ▼
┌─────────────────────────────────────────────┐
│      VAPI or RETELL (AI Voice Engine)       │
│  Natural conversation, NLP, LLM brain       │
│  Calls Make.com mid-conversation            │
│  Books Calendly appointment verbally        │
│  Works on ANY phone including landlines     │
│  ~$0.07-0.08/min                            │
└──────────┬──────────────┬───────────────────┘
           │              │
           ▼              ▼
┌──────────────┐  ┌───────────────────────────┐
│   CALENDLY   │  │      MAKE.COM             │
│              │  │                           │
│ Appointment  │  │ Mid-call: availability    │
│ booked live  │  │ check → return slots      │
│ during call  │  │                           │
│              │  │ Post-call: process        │
└──────────────┘  │ webhook, route to portal  │
                  └──────────┬────────────────┘
                             ▼
                  ┌──────────────────────────┐
                  │    FOUNDERS PORTAL       │
                  │    (Flask/PostgreSQL)     │
                  │                          │
                  │ Phone resolution chain   │
                  │ Customer match/create    │
                  │ CallLog stored           │
                  │ Tasks created            │
                  │ Pre-call brief generated │
                  │ Dashboard updated        │
                  └──────────────────────────┘
```

**Total new monthly cost (AEP estimate):**
- Twilio: ~$50-80 (pending RingCentral data pull)
- Vapi/Retell AI: ~$42-48
- ElevenLabs voice (optional): ~$5-22
- **Total: ~$100-150/month during AEP peak**
- **Off-season: ~$5-10 (just number rental)**

---


---

## 14. In-Person Appointment Recording — Google Meet Architecture

**Decision:** Fireflies replaced entirely by Google Meet native recording.
BAA already covered by Google Workspace Business Plus agreement.
Cost: $0 additional. Manual start required — same as Fireflies.

---

### Why Not Fireflies
- BAA only available on Enterprise plan ($40/user/mo)
- Enterprise also requires Private Storage add-on
- Total cost for 2 users: $80+/mo for functionality Google Meet provides free
- Not worth it when Google Workspace BAA already covers Meet

### Why Not Google Recorder App
- Pixel-only — can't mandate all agents buy a Pixel phone
- No desktop version
- Google has a well-documented history of killing first-party apps
- Not a viable multi-agent solution

### The Architecture

**Scheduling (Calendly) and Recording (Google Meet) are completely separate.**
In-person Calendly appointments show pharmacy address as location only.
No Meet link is visible to customers — zero confusion, zero explanation needed.

**Unique Meet per appointment (not a standing room):**

```
Customer books appointment via Calendly
→ Calendly webhook fires to portal
→ Portal creates unique Google Meet space via Meet REST API
   (link is NEVER sent to customer — internal use only)
→ Portal stores Meet space ID tied to this appointment record

Appointment day — Portal dashboard shows:
  "2:00pm — Bob Johnson — Cannon Pharmacy Charlotte
   [▶ Start Recording]"

Agent taps [Start Recording]:
→ Phone joins that specific Meet space
→ Auto-recording + auto-transcription start
→ Phone face-down on table, appointment proceeds normally

Appointment ends — agent leaves Meet:
→ Google Workspace Events API fires webhook to portal
→ Portal receives: transcript + recording URL + timestamps
→ Match is UNAMBIGUOUS — Meet space ID = Bob Johnson's appointment
→ No time-based fuzzy matching needed

Portal processes transcript:
→ Claude API extracts:
   - Plan discussed
   - Decision made
   - Action items with dates
   - Commitments made by agent
→ CustomerNote created on Bob's record
→ CustomerTask records created for action items
→ SendGrid fires post-appointment summary email to Bob
→ Agent dashboard updated — zero manual entry
```

**The one manual step:** Tap [Start Recording] on the portal dashboard
before the appointment begins. This is unavoidable for in-person meetings.
Everything after that tap is fully automated.

---

### Google Meet API Requirements

```python
# Creating a unique Meet space per appointment
# Uses Google Meet REST API v2

POST https://meet.googleapis.com/v2/spaces
Authorization: Bearer {oauth_token}

# Returns:
{
  "name": "spaces/abc123xyz",
  "meetingUri": "https://meet.google.com/abc-def-ghi",
  "meetingCode": "abc-def-ghi"
}

# Store meetingUri and spaces/name in Appointment record
# meetingUri is what agent opens on phone
# spaces/name is used to subscribe to Workspace Events webhook
```

**Google Workspace Events webhook for transcript ready:**
```python
# Subscribe to transcript.generated event for this meeting space
POST https://workspaceevents.googleapis.com/v1/subscriptions
{
  "targetResource": "//meet.googleapis.com/spaces/abc123xyz",
  "eventTypes": ["google.workspace.meet.transcript.v2.generated"],
  "notificationEndpoint": {
    "pubsubTopic": "projects/founders/topics/meet-transcripts"
  }
}
# Or use direct webhook via Cloud Pub/Sub → portal endpoint
```

**Transcript retrieval after webhook fires:**
```python
# Transcript saved to meeting organizer's Google Drive automatically
# Retrieve via Meet REST API:
GET https://meet.googleapis.com/v2/{transcriptName}

# Or via Google Drive API (transcripts saved as .vtt or .txt files)
GET https://www.googleapis.com/drive/v3/files/{fileId}
```

---

### Google Workspace Admin Setup Required

In Google Admin Console (admin.google.com):
- [ ] Enable Meet recording for Founders Workspace domain
- [ ] Enable Meet transcription for Founders Workspace domain  
- [ ] Set recording and transcription to auto-start (eliminates even the
      manual button click within Meet — agent just needs to join)
- [ ] Verify Business Plus plan includes recording (it does)
- [ ] Enable Google Workspace Events API in Google Cloud Console

---

### One-Party Consent — North Carolina

North Carolina is a one-party consent state for recordings. As a party to
the conversation, Tim (and all Founders agents) can legally record without
notifying the other party.

**Recommended best practice (not legally required):**
A simple verbal mention at the start: "I record my appointments for my notes —
is that okay?" takes 5 seconds and eliminates any ethical ambiguity. Nearly
all clients say yes without concern. Recommended but not mandated.

**What NOT to do:** Don't add recording disclosure to Calendly invites,
confirmation emails, or anywhere customer-facing. This creates the exact
confusion with seniors you're trying to avoid.

---

### Post-Appointment Summary Email Flow

```
Transcript lands in Google Drive
→ Workspace Events webhook → portal
→ Portal matches to Bob Johnson via Meet space ID
→ Claude API processes transcript → structured JSON:
  {
    "customer_name": "Bob Johnson",
    "plans_discussed": ["Humana Gold Plus", "UHC PPO $0"],
    "decision": "Switching to UHC PPO $0 effective Jan 1",
    "reasons": ["Doctor in network", "Lower drug costs"],
    "action_items": [
      {"task": "Submit UHC application", "due": "today"},
      {"task": "Send confirmation number to Bob", "due": "when received"}
    ],
    "follow_up_needed": true
  }
→ SendGrid fires to bob.johnson@email.com:
  Subject: "Summary of our Medicare appointment today"
  Body: Plain English recap, decisions, next steps, Tim's contact

→ CustomerNote saved to Bob's portal record
→ CustomerTask records created for each action item
→ Pipeline stage updated to "Appointed" or "Enrolled"
```

Bob receives a professional summary email without Tim typing a word.

## 15. Calendly Intake Form — New Lead Fields

```
Required:
- Full name
- Date of birth (key matching field)
- Phone number
- Email

Medicare-specific:
- Current insurance coverage type
- Current carrier and plan name (if on Medicare)
- Turning 65 within 6 months? (yes/no)
- County of residence (determines plan availability)
- Primary concern (cost/coverage/doctor/prescriptions/other)
- How did you hear about us?
- Medications to discuss? (optional free text)
- Internal staff notes (portal only, not shown to customer)
```

---

## 16. Phase 3 Build Order — FINAL

**Immediate action items (this week):**
- [ ] Pull RingCentral usage data — calls/min/SMS volume for AEP vs off-season
- [ ] Email medicare-integrations@healthsherpa.com — get webhook docs + access
- [ ] Provision Twilio account — get account SID, auth token
- [ ] Add 2GB swap file to VPS
- [ ] Update Gunicorn config to threading model
- [ ] Test Retell AI free trial — call own number, act as Medicare senior, evaluate quality

**Phase 2.5 — PostgreSQL Migration (MUST complete before Phase 3)**

This phase has been discussed but never formally scheduled. It is now a hard
prerequisite for multi-tenant architecture. Do not build Agency model or agency_id
foreign keys into SQLite — they must land in PostgreSQL from the start.

- [ ] Install PostgreSQL on NixiHost VPS
- [ ] Create `founders_portal` database and user
- [ ] Update `config.py` DATABASE_URL from SQLite to PostgreSQL
- [ ] Run `flask db upgrade` — migrate all existing tables to PostgreSQL
- [ ] Verify all existing data migrated correctly (commissions, policies, customers)
- [ ] Update `.env` with new `DATABASE_URL`
- [ ] Test full app against PostgreSQL before proceeding
- [ ] Remove SQLite dependency from `requirements.txt`
- [ ] Update `FOUNDERS_PORTAL_CONTEXT.md` section 4 to reflect PostgreSQL

**Schema migrations (Phase 3, in order — PostgreSQL only):**
- [ ] Create `Agency` model + seed Founders record
- [ ] Add `agency_id` to ALL existing tables
- [ ] Create `Household` model
- [ ] Create `CustomerPhone` model + migrate existing phone data
- [ ] Create `CallLog` model
- [ ] Create `SmsMessage` model
- [ ] Create `CustomerTask` model
- [ ] Create `UnmatchedCall` model
- [ ] Create `AgentLocation` model
- [ ] Add indexes on all phone number and agency_id fields

**Webhook handlers (Phase 3):**
- [ ] HealthSherpa enrollment webhook — HIGHEST PRIORITY
- [ ] Twilio call webhook → CallLog → phone resolution → tasks
- [ ] Twilio SMS webhook → SmsMessage → resolution chain
- [ ] Retell post-call webhook → CallLog + AI summary + action items
- [ ] Calendly booking webhook → customer match → pre-call brief
- [ ] Google Meet Workspace Events webhook → transcript → CustomerNote

**Dashboard (Phase 3):**
- [ ] Today's activity feed
- [ ] Open tasks panel
- [ ] Upcoming appointments panel
- [ ] Unmatched call queue
- [ ] Pre-call brief template
- [ ] Screen pop for incoming calls (Twilio → portal → browser push)

---

## 17. Open Questions / Things to Verify

- [ ] Does Twilio support SIP forwarding to Retell on standard account tier?
- [ ] Does NixiHost VPS firewall need ports opened for SIP traffic?
- [ ] HealthSherpa carrier list — confirm UHC, Humana, Aetna, BCBS NC, Devoted, Healthspring all present
- [ ] FMO contractual requirement for MedicareCENTER vs HealthSherpa freedom to switch?
- [ ] Captive join code process — how do agents join Founders HealthSherpa account?
- [ ] Calendly plan tier — does current plan support API calls from Retell mid-call?
- [ ] RingCentral number porting timeline — how long does it take, avoid gap during AEP?
- [ ] Retell AI quality test — does it handle natural Medicare senior conversation well?
- [ ] 1099 contractors vs W2 agents — any difference in HealthSherpa captive account setup?

---

## 18. Security & HIPAA Compliance Checklist

### Legal Context

Medicare client data — names, DOBs, MBIs, plan information, health conditions —
is PHI under HIPAA. As a Medicare agent you're already a Business Associate.
As a software platform storing PHI for OTHER agencies, you become a Business
Associate to those agencies with direct legal liability.

The HIPAA Security Rule was overhauled in 2026 with a compliance deadline of
February 16, 2026. New mandatory requirements: encryption at rest AND in transit
(was "addressable," now mandatory), multi-factor authentication for all PHI access,
annual documented compliance audits, updated BAAs with all business associates.
Build to the new standard from day one — don't build to the old standard and retrofit.

---

### Phase A — Internal Use Only (Founders) — Before AEP 2026

**Immediate technical items:**
- [ ] Verify `.env` was NEVER committed to GitHub
      `git log --all --full-history -- .env`
      If it appears: rotate ALL keys immediately, purge from git history
- [ ] Database encryption at rest — encrypt PostgreSQL disk volume at OS level
      OR use pgcrypto for column-level encryption on PHI fields
- [ ] SSL/TLS auto-renewal verified (Let's Encrypt expires June 15, 2026)
- [ ] VPS hardening:
      SSH key auth only — disable password login
      Install fail2ban
      ufw firewall: allow only ports 22, 80, 443
      Regular apt update/upgrade schedule
- [ ] IDOR protection on EVERY route — every query must include agency_id:
      `Customer.query.filter_by(id=id, agency_id=current_user.agency_id).first_or_404()`
- [ ] HMAC signature verification on ALL webhook endpoints
      (HealthSherpa, Dialpad, Retell, Calendly, Google Meet)
- [ ] Flask-Limiter rate limiting — prevents DDoS and runaway webhook loops
- [ ] Flask SECRET_KEY is a long random string — not 'dev' or any guessable value
- [ ] Zero raw SQL f-strings — always SQLAlchemy ORM parameterized queries
- [ ] Automated encrypted daily database backups to off-server location
      (Google Cloud Storage or S3 — NOT on same VPS)
- [ ] UptimeRobot (free) — 24/7 uptime monitoring with SMS alerts
- [ ] Multi-factor authentication for portal admin accounts
- [ ] Session timeout after inactivity (30 min recommended)
- [ ] Audit log captures: who, what, when, from which IP on all PHI access

**Business Associate Agreements — must be signed before handling PHI:**
- [ ] NixiHost — contact them, ask if they'll sign a BAA
      If they won't: plan migration before white-label launch
- [ ] Google Workspace — Business Plus supports BAAs, verify it's executed
- [ ] SendGrid/Twilio — BAAs available on certain plans, verify your tier
- [ ] Retell AI — check HIPAA compliance documentation
- [ ] HealthSherpa — they handle PHI, verify their BAA process
- [x] ~~Fireflies~~ ELIMINATED — BAA Enterprise-only ($40/user/mo + Private Storage required). Replaced by Google Meet native recording.
- [ ] Calendly — BAAs on Teams plan and above
- [ ] Dialpad — verify HIPAA compliance tier and BAA availability

---

### Phase B — Before First Outside Agency Gets Access

**Legal (attorney-reviewed):**
- [ ] Privacy Policy
- [ ] Terms of Service
- [ ] Data processing addendum template for agency customers
- [ ] Incident response plan (HIPAA requires 60-day breach notification to HHS)
- [ ] Annual HIPAA compliance audit process documented
- [ ] Data retention and deletion policy
- [ ] Data export capability built — agencies must be able to leave with their data

**Insurance:**
- [ ] Tech E&O (Errors & Omissions) insurance as a software vendor
- [ ] Cyber liability insurance

**Infrastructure:**
- [ ] Migrate from NixiHost $5 VPS to managed HIPAA-friendly hosting
      (DigitalOcean $20-50/mo, Render, AWS, or Google Cloud)
      NixiHost is fine for Founders internal. Not defensible for paying customers.
- [ ] PostgreSQL as a managed database service, not self-hosted on app server
- [ ] Separate staging environment from production
- [ ] Formal deployment pipeline beyond manual git pull

**Multi-tenant security:**
- [ ] Penetration test or security audit before launch
- [ ] Verify complete data isolation between agencies across all query paths
- [ ] Demo/sandbox agency with fake data only — zero real PHI for sales prospects
- [ ] Agent offboarding process: data export + deletion + confirmation documented

---

## 19. Things You Haven't Asked That Could Bite You

### CMS Marketing Rules — Separate from HIPAA, Equally Dangerous

CMS has strict marketing regulations for Medicare agents beyond HIPAA:
- **Call recording disclosure** — callers must be informed they're being recorded.
  Your Retell AI scripts MUST include this disclosure verbally.
- **TPMO disclosure** — Third Party Marketing Organization disclosure required
  on all marketing materials including automated voice scripts
- **SOA requirements** — AI-handled calls that discuss plan options may trigger
  SOA requirements. Define clearly what Retell is authorized to discuss.
- **Robocall restrictions** — automated outbound calling to Medicare beneficiaries
  is heavily regulated under TCPA and CMS rules. Don't run outbound AI campaigns
  without reviewing 2026 CMS Communications and Marketing Guidelines first.

**One non-compliant AI script running 200 times during AEP = 200 violations.**
Review CMS guidelines before configuring any Retell AI scripts. This is not optional.

---

### Agent Departure / Data Ownership

When an AOR agent leaves Founders, what happens to their BOB in the portal?
- Commission history stays — Founders owns override records
- AOR agents may legally own their BOB — this is already in your AOR vs LOA model
- Need a documented offboarding process before anyone uses the portal
- Brian specifically: cannibalization concerns already documented, departure
  scenario should be defined before he has meaningful portal access

---

### RingCentral Call Data — What You Learned

From your actual October-December 2025 RingCentral data (Tim only):

| Month | Total Calls | Inbound | Outbound | Total Minutes |
|---|---|---|---|---|
| October (AEP peak) | 293 | 175 | 118 | 1,597 |
| November | 232 | 160 | 72 | 813 |
| December | 209 | 133 | 76 | 1,172 |

**The critical number: 77.1% of inbound calls went to voicemail or were missed.**
In October alone: 122 out of 175 inbound calls unanswered. That's the problem
Retell AI solves. Those are missed appointments and missed commissions.

Outbound minutes (1,073) were double inbound minutes (524) in October — you
spent twice as long calling people back as taking inbound calls.

**Twilio cost estimate for October at Tim's volume:**
- Inbound 524 min × $0.0085 = $4.45
- Outbound 1,073 min × $0.013 = $13.95
- SMS 390 segments × $0.0079 = $3.08
- Phone number = $1.15
- **October total: ~$22.63 vs ~$45-50 RingCentral plan**
- For 4-5 agents at similar volume: ~$90-115/mo vs $180-250/mo — roughly 50% savings

Full cost model pending RingCentral data pull for all agents.

---

### HealthSherpa Agency Account Structure — Confirmed

Two join codes, use correctly:

**Captive join code** → Mike, Betty, Anjana (LOA agents)
- Full Book access to all Contacts and PHI in webhook payload

**Independent join code** → Tim, Chris, Rebekah, Justin, Brian (AOR agents)
- Per-carrier join, limited Contact data in webhook (name, state, zip, enrollment)
- Webhook payload is LESS rich for AOR agents — portal must handle this gracefully

**Tidewater Management Group confirmed:**
- Owned by Integrity Marketing Group
- Pushes Integrity technology suite (MedicareCENTER, PlanEnroll, IntegrityCONNECT)
- BUT: no contractual requirement to use Integrity enrollment platforms
- Founders agents can use HealthSherpa freely — confirmed by Tim

**HealthSherpa MCP for Claude Code:**
```bash
claude mcp add --transport http HealthSherpa-Medicare-Docs \
  https://docs.medicare.healthsherpa.com/~gitbook/mcp
```
Add this to your development environment before building the webhook handler.
Claude Code will have live HealthSherpa API docs available during development.

---

### Competitor Landscape — Know What Exists

- **ProducerMAX** — Medicare-specific CRM, HIPAA compliant, AWS-hosted, exists today
- **AgencyZoom** — general insurance CRM, some Medicare agents use it
- **Onyx** — telephonic sales focused, HealthSherpa integration, built for call centers
- **GoHighLevel** — generic CRM agents hack for Medicare use, HealthSherpa just added native integration

**Your moat:** commission audit against carrier statements, 6-carrier BOB import,
MBI-based matching, household-aware phone resolution, AEP automation — none of
these exist in any competitor. Built by an active Medicare agent who understands
D-SNP eligibility, AOR vs LOA, Humana ID masking, and BCBS term date quirks.

---

### The Commission Audit as Anchor Feature

Your PRODUCT_VISION.md lists commission auditing as one feature among many.
Reconsider positioning it as the anchor of the sales pitch:

*"The commission audit pays for itself. One caught discrepancy per year covers
the entire annual subscription. Everything else is free."*

For any agency processing $500K+ in commissions annually, a 1% error rate is
$5,000/year in uncaught discrepancies. Your $249/mo subscription is $2,988/yr.
The math is instant and requires no further selling.

---

### Honest Buildout Timeline

**Now → AEP 2026 (October):**
- PostgreSQL migration (Phase 2.5 — hard prerequisite)
- HealthSherpa agency account + webhook
- Dialpad + Retell integration
- Unified comms dashboard
- Compensation conversation with AJ
- Founders agents adopt HealthSherpa

**AEP 2026 (Oct-Dec):**
- Real-world stress test with 8 agents
- Gather specific metrics: appointments booked by AI, commission discrepancies caught
- Fix everything that breaks in production

**Q1 2027:**
- BAAs signed with all vendors
- Legal docs (Privacy Policy, ToS) attorney-reviewed
- Infrastructure upgrade from NixiHost
- First outside agency — controlled beta, 1-2 agencies max

**Q2-Q3 2027:**
- Tidewater presentation — with receipts, not promises
- 5-10 paying agencies
- Tech E&O + cyber liability insurance

**Q4 2027:**
- FMO partnership conversations
- White-label licensing pitch to Tidewater or similar FMOs

**The Tidewater play:** Don't present until you have 2-3 non-Founders agencies
using it successfully. One agency is a pilot. Two or three is a product.
The FMO white-label pitch is not a $99/mo sale — it's a $10K-50K/yr enterprise
contract covering their entire agent network. That conversation happens after
you have proof, not before.

---

*This document supersedes SESSION_UPDATE_2026-03-23.md entirely.*
*Merge into FOUNDERS_PORTAL_CONTEXT.md (sections 3, 4, 9, 13, 17, 18)*
*Merge into PRODUCT_VISION.md (sections 4, 6, 7, 8, 10, 11, 13)*

*Priority starting point for next Claude Code session:*
*1. Add HealthSherpa MCP to Claude Code environment*
*2. PostgreSQL migration (Phase 2.5)*
*3. HealthSherpa agency account setup*
*4. VPS security hardening + swap file*
*5. HealthSherpa webhook endpoint*
