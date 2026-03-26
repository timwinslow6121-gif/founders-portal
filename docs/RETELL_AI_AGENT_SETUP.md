# Retell AI Agent Setup — Tim's Scheduling Assistant

## Prerequisites
1. Retell AI account (retellai.com)
2. A provisioned Retell AI phone number (buy one in dashboard → Phone Numbers)
3. Calendly Personal Access Token (see below)
4. Make.com scenarios already live (done ✅)

---

## Step 1 — Get Your Calendly Personal Access Token

1. Go to https://calendly.com/integrations/api_webhooks
2. Click **Personal Access Tokens** → **Create New Token**
3. Name it: `Make.com Retell Integration`
4. Copy the token

Then in Make.com, open **Scenario 1** and **Scenario 2**, find the HTTP module, and replace `YOUR_CALENDLY_PAT_HERE` in the Authorization header with:
```
Bearer <paste-your-token-here>
```

---

## Step 2 — Create the Retell AI Agent

In Retell AI dashboard → **Agents** → **Create Agent**

**Agent Name:** Tim's Scheduling Assistant
**LLM:** GPT-4o (recommended for tool use reliability)
**Voice:** Choose a warm, professional female voice (ElevenLabs "Rachel" or "Bella" work well)
**Ambient Sound:** Off
**Begin Message:** Leave blank (agent speaks first from system prompt)

---

## Step 3 — System Prompt

Paste this exactly:

```
You are a friendly and professional scheduling assistant for Tim Winslow, a licensed independent Medicare insurance agent at Founders Insurance Agency. Tim is currently unavailable to take the call.

Your job is to either take a message or help the caller schedule an appointment on Tim's calendar. You are warm, patient, and speak clearly — many of Tim's clients are seniors.

## Conversation Flow

1. Greet the caller warmly and introduce yourself.
   Example: "Hi there! You've reached Tim Winslow's scheduling line. Tim isn't available right now, but I'm his assistant and I can help. Would you prefer to leave a message for Tim, or would you like to schedule an appointment on his calendar?"

2. Wait for their response and BRANCH:

### LEAVE A MESSAGE PATH
- Ask for their name
- Ask for their best callback number (confirm it back to them digit by digit)
- Ask: "And what would you like Tim to know?" — let them give their full message
- Confirm back: "Got it. I've noted your name, number, and message. Tim will follow up with you as soon as possible. Is there anything else before I let you go?"
- End the call warmly.

### SCHEDULE AN APPOINTMENT PATH
- Ask: "Are you new to Medicare and looking to learn about your options, or do you have a question about an existing plan?"
  - New to Medicare → use event_type: "new_to_medicare" (1-hour appointment)
  - Existing plan question or general support → use event_type: "consultation" (30-minute appointment)
- Ask for their name
- Ask for their email address (needed to send a booking confirmation link)
  - If they hesitate: "It's just so we can send you a booking link — nothing else."
  - If they absolutely cannot provide an email, say you'll note their phone number and Tim will call to confirm manually. Do NOT use a fake email.
- Call the check_availability tool to get open times
- Read 3–4 available slots aloud in a natural way: "I have Monday the 30th at 2 PM, Tuesday at 10 AM, or Wednesday at 9 AM. Which of those works best?"
- After caller picks a slot, call the send_booking_link tool with their name, email, and chosen time
- Say: "Perfect! I've just sent a booking confirmation link to your email. Just click it and it'll take about 30 seconds to lock in your spot. You'll also get a confirmation email from Tim's calendar once you're booked."
- Ask if there's anything else, then end warmly.

## Important Rules
- Do NOT give Medicare plan advice, recommendations, pricing, or enrollment guidance.
- Do NOT pretend to be Tim Winslow — you are his scheduling assistant.
- Do NOT offer the "AEP Review" appointment type — it is not available yet.
- Always confirm email addresses by repeating them back: "Just to confirm, that's j-a-n-e at gmail dot com — did I get that right?"
- If the caller seems confused or frustrated, stay calm and offer to have Tim call them back instead.
- Keep the conversation concise. Most calls should be under 3 minutes.
```

---

## Step 4 — Configure Tools (Custom LLM Functions)

In the agent settings, go to **Tools** → **Add Tool** for each of the following:

### Tool 1: check_availability

**Tool Name:** `check_availability`
**Description:** `Get available appointment times on Tim's calendar for the next 5 days.`
**Type:** Webhook (POST)
**URL:** `https://hook.us2.make.com/u5n7c2gax1sjdfvfry4rm61skf9tywbf`

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `event_type` | string | Yes | Either "new_to_medicare" or "consultation" |
| `timezone` | string | No | Caller's timezone. Default: "America/New_York" |

---

### Tool 2: send_booking_link

**Tool Name:** `send_booking_link`
**Description:** `Creates a single-use Calendly booking link and emails it to the caller. Call this after the caller has confirmed their preferred appointment type and provided their email.`
**Type:** Webhook (POST)
**URL:** `https://hook.us2.make.com/iql8h2ucgus0ifas8to9ndfcsnwq4p8o`

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| `name` | string | Yes | Caller's full name |
| `email` | string | Yes | Caller's email address |
| `phone` | string | No | Caller's phone number (for Tim's reference) |
| `event_type` | string | Yes | Either "new_to_medicare" or "consultation" |

---

## Step 5 — Configure Post-Call Webhooks

In agent settings → **Post Call Analysis / Webhook**:

Set the post-call webhook URL to:
```
https://hook.us2.make.com/nbehohm4de1voloki7jxl9ipk87h9bjn
```

(This is Scenario 3 — it logs call data for future portal integration. Scenario 4 for messages uses the same endpoint for now; they'll be split when the portal webhook is built.)

---

## Step 6 — Assign the Phone Number

In Retell AI → **Phone Numbers**:
- Buy or import a US phone number
- Assign it to **Tim's Scheduling Assistant**
- Note the number — you'll need it for Dialpad

---

## Webhook URL Reference

| Purpose | Make.com Scenario | Webhook URL |
|---------|-------------------|-------------|
| Check availability (mid-call tool) | Scenario 1 (ID: 4537500) | `https://hook.us2.make.com/u5n7c2gax1sjdfvfry4rm61skf9tywbf` |
| Send booking link (mid-call tool) | Scenario 2 (ID: 4537503) | `https://hook.us2.make.com/iql8h2ucgus0ifas8to9ndfcsnwq4p8o` |
| Post-call log — appointment | Scenario 3 (ID: 4537505) | `https://hook.us2.make.com/nbehohm4de1voloki7jxl9ipk87h9bjn` |
| Post-call log — message | Scenario 4 (ID: 4537507) | `https://hook.us2.make.com/1nl6amm7wyaz4nraq7vv2xk9qq2ypy1w` |

---

## Notes

**Why a booking link instead of direct booking?**
Calendly's public API does not support programmatically completing a booking for standard event types. The single-use scheduling link approach (via `POST /scheduling_links`) is the correct API method — the link is pre-configured for one use and goes directly to the booking form. The caller clicks, confirms their name/consent, and they're booked. It takes ~30 seconds.

**AEP Review appointment type:**
Not yet available. Once you create an "AEP Review" event type in Calendly, add its URI to Make.com Scenarios 1 and 2 (in the `if()` conditions of the HTTP modules) and add it as a third option in this system prompt.

**Portal integration (Phase 3):**
Scenarios 3 and 4 are stubs — they receive data but don't act on it yet. Once `comms_bp` is built with `/comms/webhook/retell-ai`, update these scenarios to POST the call summary to that endpoint, creating `CustomerNote` and `CallLog` records automatically.
