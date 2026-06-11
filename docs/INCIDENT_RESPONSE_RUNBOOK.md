# Founders Portal — Incident Response Runbook

**Who this is for:** Tim (technical owner + Google Workspace super-admin).
**When to open it:** you got a 🔔 *Founders Portal Security Alert* email, or you
saw something off in the Audit Log.
**The one principle:** every alert email tells you whether access was **granted
or blocked**. Most say *blocked* → already handled, no panic. This runbook is for
the rare case where you need to *do* something.

Last updated 2026-06-10 (S2). Plain-English on purpose — follow the steps in order.

---

## 0. First 30 seconds — triage (always do this first)

1. **Read the alert email's "Access granted?" line.**
   - **"NO — blocked"** → the portal already stopped it. Breathe. Go to the
     matching section below only if it's *repeating* or you want to look closer.
   - Anything suggesting access *was* granted to someone who shouldn't have it →
     treat as a real incident, go straight to §3 (Lock down an account).
2. **Open the Audit Log** to see the extent: portal → admin sidebar → **Audit
   Log** (or `https://portal.foundersinsuranceagency.com/admin/audit-log`).
   Filter by **category** or **severity** (pick `alert`) and look at the **IP**
   and **Detail** columns. This is your "what actually happened" view.

That's the whole triage. Now go to the section matching your alert.

---

## 1. Alert: "login attempt blocked" (non-domain / failed login)

**What it means:** someone tried to sign in with a Google account that is **not**
`@foundersinsuranceagency.com`, or a login failed. The portal blocks every
non-Founders account automatically, so **no access was granted.**

**What to do:**
- **One or a few of these:** nothing. It's noise — a wrong Google account, a
  mistyped login, a random internet scan. The door held.
- **Many of them from the SAME IP in a short time:** someone is probing. Note the
  IP from the email / Audit Log and block it → **§4 (Block an IP)**.
- It is **never** necessary to change anything about an agent's account for this
  alert — no Founders account was involved.

---

## 2. Alert: "rate-limit flood" (429 flood from one source)

**What it means:** one IP is hammering the portal fast — a bot, a scanner, or a
denial-of-service attempt. **S1's rate limiter is already auto-blocking it**
(that's *why* you got the alert — it tripped the limiter). No access granted.

**What to do:**
- **Usually nothing** — the limiter is doing its job; the flood gets 429'd and
  typically gives up. The alert is an FYI.
- **If it persists** (you keep getting these, or the portal feels slow for real
  agents): block that IP at the firewall → **§4 (Block an IP)**.
- Check the Audit Log filtered to `category = security` to see how many hits and
  from where.

---

## 3. Lock down an account (suspected compromised agent)

**Use this when:** the Audit Log shows an agent account doing something it
shouldn't — e.g. viewing customers it never touches, a huge export it didn't
make, or activity you *know* that person didn't do. The fear: their Google
credentials were stolen.

**The portal is Google-login-only, so the fastest kill switch is Google.**
Suspending their Google account instantly locks them out of the portal too.

**Steps:**
1. Go to **admin.google.com** (you're super-admin) → **Directory → Users**.
2. Click the agent.
3. **Sign out** (top menu / "Sign out" — kills their active Google sessions
   immediately), AND
4. **Suspend user** (blocks all future login until you un-suspend). This is the
   hard stop — they cannot log into the portal while suspended.
5. Back in the portal **Audit Log**, filter to that user (and/or their IP) and
   read **everything they touched** — note customer names/IDs in the Detail
   column and any export `record_count`. This is your "extent of exposure" list.
6. When safe (you've confirmed it was them / reset their password / it's
   resolved), **un-suspend** in the same Google Users screen.

**Force EVERY user to re-login (nuclear option):** if you think multiple sessions
or the portal itself is compromised, rotate the portal's secret key — this
invalidates **all** active portal sessions at once, so everyone must log in fresh
via Google:
```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
cd /var/www/founders-portal
# back up .env first
cp .env .env.bak.$(date +%Y%m%d%H%M)
# generate a new key and replace the SECRET_KEY line
NEWKEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$NEWKEY/" .env
systemctl restart founders-portal
```
After this, every agent simply logs in again with Google — no data is lost; only
sessions are reset.

---

## 4. Block an IP (copy-paste)

**Use this when:** a single IP is probing logins (§1) or flooding (§2) and won't
stop. The VPS uses **ufw** (already active).

```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
# replace 203.0.113.9 with the real IP from the alert / Audit Log
ufw deny from 203.0.113.9
ufw status numbered      # confirm the rule is there
```

**To undo it later** (the IP was fine, or the threat passed):
```bash
ufw status numbered          # find the rule number for that IP
ufw delete <number>          # e.g. ufw delete 3
```

**Alternative (block at the web server instead of the firewall)** — if you'd
rather return "403 Forbidden" than drop the packet:
```bash
ssh -i ~/.ssh/id_ed25519 root@23.187.248.100
# add a deny line inside the server { } block, then reload
nano /etc/nginx/sites-available/founders-portal   # add:  deny 203.0.113.9;
nginx -t && systemctl reload nginx                # test config, then reload
```
`ufw deny` is the simpler, recommended choice. Use one or the other, not both.

---

## 5. Assess the extent (the Audit Log is your investigation tool)

Whenever you need to answer *"what did this account/IP actually do?"*:

1. Portal → **Audit Log**.
2. Filter by **severity = alert** to see flagged events, or browse all.
3. Read the **IP**, **User**, **Detail**, and **Count** columns. The Detail
   column carries the specifics — e.g. `viewed customer profile [customer #842]`,
   or `customer CSV export` with a **Count** of how many records.
4. To trace one actor: note their IP/user and scan every row that matches — that
   list **is** the extent of what they saw or took.

The log is append-only (nothing in the portal edits or deletes audit rows), so
it's a trustworthy record.

---

## 6. If PHI may have been exposed (real breach)

If your investigation shows a non-authorized party actually **viewed or exported
customer PHI** (names + Medicare numbers / DOB / health info):

- **This is a potential HIPAA breach.** PHI exposure can carry legal
  breach-notification obligations (notifying affected individuals, and possibly
  HHS, within set timeframes).
- **This runbook does not give legal advice.** Treat a confirmed PHI exposure as
  serious: preserve the Audit Log evidence (don't delete anything), write down
  what you found (which records, when, by whom), and consult a
  HIPAA-compliance/legal resource before deciding on notifications.
- Loop in **Brian (owner)** for any confirmed breach — it's his agency and his
  call on business/legal response.

---

## 7. Who responds

- **Primary responder: Tim** (technical owner + Workspace admin) — runs the steps
  above.
- **Confirmed breach: loop in Brian (owner)** for the business/legal decision.
- (No external IT/compliance contact named yet — add one here when you have one.)

---

## Quick reference

| Alert | Access granted? | Default action |
|---|---|---|
| Login attempt blocked (non-domain/failed) | No | Nothing; block IP (§4) only if many from one IP |
| Rate-limit flood (429) | No | Nothing; block IP (§4) if it persists |
| Suspicious activity by a Founders account (from the log) | Maybe | Suspend in Google (§3) + assess extent (§5) |

**Three levers, in order of reach:** block one IP (§4) → suspend one account
(§3) → rotate SECRET_KEY to reset all sessions (§3, nuclear). Start with the
smallest that fits.
