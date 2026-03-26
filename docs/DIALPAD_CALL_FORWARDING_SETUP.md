# Dialpad Call Forwarding Setup — Route Missed Calls to Retell AI

## What This Does
When Tim's Dialpad number rings and goes unanswered (after ~4 rings / 20 seconds), the call automatically forwards to the Retell AI scheduling assistant instead of voicemail.

## Prerequisites
- Retell AI phone number provisioned (from RETELL_AI_AGENT_SETUP.md Step 6)
- Dialpad admin access

---

## Setup Steps

### 1. Open Dialpad Admin Settings
- Go to https://dialpad.com
- Click your profile → **Admin Settings** (or go to **admin.dialpad.com**)

### 2. Navigate to Your Line Settings
- In the left sidebar → **Users**
- Find and click **Tim Winslow**
- Click **Call Handling** (or **Routing**)

### 3. Configure Unanswered Call Forwarding
Under **When a call is not answered:**

- Set **Ring for:** `20 seconds` (4 rings)
- Set **Then forward to:** `Phone number`
- Enter the Retell AI phone number (from Step 6 of Retell setup)
- **Disable voicemail** for this forwarding rule (Retell AI is the fallback — voicemail should not compete)

### 4. Disable Tim's Voicemail (Recommended)
To ensure ALL missed calls hit Retell AI:
- In the same Call Handling settings, find **Voicemail**
- Set voicemail to **Off** or set the greeting to redirect callers to call back
- Alternative: Keep voicemail enabled but set ring time to 40+ seconds so Retell AI always answers first

### 5. Save and Test
- Save your settings
- Call Tim's Dialpad number from a different phone
- Let it ring — after ~20 seconds, Retell AI should pick up
- Say "I'd like to schedule an appointment" and walk through the flow

---

## Troubleshooting

**Retell AI isn't picking up:**
- Verify the Retell AI phone number is correctly entered in Dialpad (include country code: +1)
- Confirm the Retell AI agent is published (not just saved as a draft)
- Check that the phone number is assigned to the agent in Retell dashboard

**Caller hears 1-2 seconds of silence after transfer:**
- This is normal — it's the PSTN handoff time. The Retell AI agent is configured to speak first immediately, so the silence is brief.

**Calls going to voicemail instead of Retell:**
- Check the ring duration — if voicemail picks up before 20 seconds, extend voicemail ring time or disable it entirely

---

## Call Flow Summary

```
Caller dials Tim's Dialpad number
    ↓ rings 20 seconds (~4 rings)
    ↓ Tim doesn't answer
Dialpad forwards to Retell AI number
    ↓ Retell AI picks up immediately
    ↓ "Hi, you've reached Tim Winslow's scheduling line..."
    ↓
    ├── Leave a message → message logged, Tim follows up
    └── Book appointment → Make.com checks Calendly → email sent with booking link
                                     ↓
                          Caller clicks link, books themselves
                                     ↓
                          Calendly sends confirmation email + reminders
```
