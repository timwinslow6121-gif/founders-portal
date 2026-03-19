# Medicare Agency Management System (MAMS)
## Product Vision — White Label SaaS
*Started: March 2026 · Testing ground: Founders Insurance Agency*

---

## 1. The Problem

Medicare insurance agencies currently use generic CRM tools (Zoho, HubSpot, Salesforce) that were built for software salespeople, not Medicare agents. None of them understand:

- Carrier BOB exports and their inconsistent formats
- Commission split structures and AOR assignment
- MBI as a cross-carrier customer identifier
- Medicaid levels and their impact on plan eligibility
- SOA compliance requirements
- AEP communication workflows
- Partner pharmacy relationships
- The difference between AOR and LOA agents

The result: agents spend hours every month normalizing spreadsheets, manually verifying commission math, hunting for customer records across carrier portals, and losing leads because they have no automation during AEP.

---

## 2. The Solution

A **purpose-built Medicare Agency Management System** that replaces Zoho entirely for this vertical. Built by a Medicare agent, for Medicare agents.

**What makes it different from every other CRM:**
- Carrier BOB auto-import (UHC, Humana, Aetna, BCBS, Devoted, Healthspring)
- Commission audit that verifies split math to the penny per carrier
- AOR ownership history with cannibalization detection
- MBI-based customer master that survives carrier changes
- Medicaid level tagging with plan eligibility logic
- Partner pharmacy relationship tracking
- SOA management (send, track, store)
- MedicareCenter enrollment PDF OCR → auto-match to customer record
- AEP communication automation (SMS auto-reply, Calendly, Fireflies)
- Built for non-technical users (60-year-old agents who struggle with spreadsheets)

---

## 3. Target Market

**Primary:** Independent Medicare insurance agencies (1-20 agents)
- Estimated 15,000-20,000 such agencies in the US
- Currently using Zoho ($50-300/agent/month) or spreadsheets
- Pain points: commission reconciliation, AEP chaos, customer data quality

**Secondary:** FMOs (Field Marketing Organizations) who manage networks of agents
- Could white-label for their entire agent network
- Volume licensing opportunity

**Tertiary:** Individual Medicare agents (solo practitioners)
- Lighter version with fewer multi-agent features
- Lower price point

---

## 4. Pricing Model

### Per-Agency SaaS
| Tier | Agents | Price/mo | Notes |
|---|---|---|---|
| Solo | 1 agent | $99/mo | Individual practitioner |
| Small Agency | 2-5 agents | $249/mo | Most independent agencies |
| Agency | 6-15 agents | $499/mo | Founders-sized |
| Enterprise | 15+ agents | Custom | FMOs, large agencies |

### Add-On Modules
| Module | Price/mo | Notes |
|---|---|---|
| Communication Hub | $99/mo | SMS campaigns, auto-reply, Calendly |
| Email Campaigns | $49/mo | SendGrid-powered, CMS-compliant templates |
| SOA Management | $49/mo | Send, track, store, 10-year compliant |
| Fireflies Integration | $29/mo | Meeting summaries → customer records |

### Setup Fee
- $500 one-time onboarding fee per agency
- Includes: data import from existing CRM, carrier parser configuration, training

---

## 5. Feature Roadmap (Phased)

### Phase 1 — Core (Founders testing ground, current build)
- [x] Carrier BOB import (6 carriers)
- [x] Agent dashboard (per-agent filtered)
- [x] Admin overview (agency-wide)
- [x] Commission audit (5 carriers, per-agent split rates)
- [x] Agent settings (contracts, splits, IDs)
- [x] Birthday labels (Avery 5160 PDF)
- [ ] Upcoming terminations page
- [ ] Customer master database
- [ ] Editable customer records
- [ ] Customer profile page

### Phase 2 — Customer Intelligence
- [ ] AOR ownership history
- [ ] Cannibalization detection and alerts
- [ ] Point of contact management (POC ≠ patient)
- [ ] Pharmacy master list + customer tagging
- [ ] Medicaid level tagging + plan eligibility
- [ ] MedicareCenter PDF OCR → customer matching
- [ ] Deal stage tracking (Lead → SOA → Enrolled → Effective → Termed)
- [ ] Carrier plan master database (H-numbers, coverage, star ratings)

### Phase 3 — Compliance
- [ ] SOA creation and sending (CMS-compliant)
- [ ] SOA signature tracking
- [ ] 10-year document storage
- [ ] MedicareCenter SOA reference integration
- [ ] Audit trail for all customer interactions
- [ ] CMS-compliant email templates

### Phase 4 — Communication Automation
- [ ] RingCentral integration (call logs, SMS, auto-reply configuration)
- [ ] Calendly per-agent booking pages
- [ ] Automated reminder sequences (pre-appointment SMS/email)
- [ ] Post-appointment follow-up automation
- [ ] Fireflies.ai webhook → meeting summary → customer record
- [ ] SMS template library (AJ/admin-approved)
- [ ] Email campaign module (filter by carrier, plan, renewal date, birthday)
- [ ] "Who's calling?" lookup by phone number

### Phase 5 — Analytics & Forecasting
- [ ] Commission forecast (Part D + supplement rates)
- [ ] AEP performance tracking per agent
- [ ] Retention rates by carrier and plan
- [ ] Churn risk scoring
- [ ] Lead source tracking (pharmacy referrals, self-generated, etc.)
- [ ] Agency revenue dashboard (gross, splits, pharmacy rent)
- [ ] Year-over-year BOB growth

### Phase 6 — White Label
- [ ] Multi-tenant architecture (each agency = isolated data)
- [ ] Custom branding per agency (logo, colors)
- [ ] Admin portal for MAMS operator (manage agencies, billing)
- [ ] Stripe billing integration
- [ ] Onboarding wizard for new agencies
- [ ] FMO bulk provisioning
- [ ] API for FMO integrations

---

## 6. Technical Architecture for White Label

### Current (Single Tenant)
```
One Flask app → One SQLite DB → One agency (Founders)
```

### Future (Multi Tenant)
```
Option A: Schema per tenant (PostgreSQL schemas)
  - One DB, isolated schemas per agency
  - Easy backups, moderate complexity

Option B: DB per tenant
  - One SQLite/PostgreSQL per agency
  - Maximum isolation, harder to manage at scale

Option C: Tenant ID column on all tables
  - Simplest to build, most risk if query misses tenant filter
  - Not recommended for sensitive financial data

Recommendation: PostgreSQL with schema-per-tenant
  - Migrate from SQLite first (already on roadmap)
  - Each agency gets: founders_portal_AGENCYID schema
  - Shared: users auth, billing, global carrier plan database
```

### Infrastructure for Scale
```
Current:  1 VPS ($5/mo) → 1 agency
10 agencies: Same VPS upgraded ($20/mo) → fine
50 agencies: DigitalOcean Managed PostgreSQL + App Platform ($100/mo)
200+ agencies: AWS RDS + ECS or similar → proper DevOps needed
```

---

## 7. Competitive Landscape

| Product | Price | Medicare-Specific | Commission Audit | BOB Import | AOR Tracking |
|---|---|---|---|---|---|
| **MAMS (ours)** | $99-499/mo | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| Zoho CRM | $50-300/agent | ❌ Generic | ❌ No | ❌ No | ❌ No |
| AgencyZoom | $149-499/mo | Partial | ❌ No | ❌ No | Partial |
| HubSpot | $90-800/mo | ❌ Generic | ❌ No | ❌ No | ❌ No |
| MedicareCenter | Free-$99/mo | ✅ Yes | ❌ No | ❌ No | ❌ No |
| Salesforce | $300+/agent | ❌ Generic | ❌ No | ❌ No | ❌ No |

**Key insight:** No product in the market does commission audit against carrier statements. That alone is a differentiator that pays for itself — one caught discrepancy per year justifies the subscription.

---

## 8. Go-To-Market Strategy

### Phase 1: Founders as living proof of concept
- Build and refine with real Founders data
- Document every pain point solved
- Quantify: "Commission audit caught $X in discrepancies," "AEP automation booked Y% more appointments"

### Phase 2: FMO partnerships
- FMOs (Field Marketing Organizations) manage hundreds of agencies
- One FMO partnership = instant access to their entire agent network
- Offer FMO a revenue share for referrals or bulk licensing

### Phase 3: Medicare agent communities
- Facebook groups (Medicare Insurance Agents, etc.) — very active
- NABIP (National Association of Benefits and Insurance Professionals)
- State insurance association events
- Direct outreach to agency owners

### Phase 4: Content marketing
- "How I automated my AEP and booked 40% more appointments" — Tim's story
- YouTube: tutorials on carrier BOB normalization, commission verification
- Positions Tim as the go-to tech person in the Medicare agent space

---

## 9. Legal and Compliance Considerations

- **HIPAA:** Customer data includes DOB, Medicare ID, health plan info — technically PHI. Need BAA with all data processors (hosting, SendGrid, etc.) before selling to other agencies.
- **CMS Marketing Rules:** SOA templates must be CMS-compliant. Cannot help agents circumvent the 48-hour rule technically — only streamline compliant workflows.
- **State Insurance Regulations:** Each state has its own rules about agent communication and record keeping. SOA storage requirements vary.
- **E&O Insurance:** As a software vendor serving insurance agents, may need tech E&O coverage.
- **Data Ownership:** Each agency's data must be clearly isolated and exportable. Agencies must be able to leave and take their data.

---

## 10. Revenue Projections

### Conservative (Year 1 post-launch)
- 10 agencies × $249/mo average = $2,490/mo = **$29,880/year**
- Plus setup fees: 10 × $500 = $5,000
- **Year 1 total: ~$35,000**

### Moderate (Year 2)
- 50 agencies × $299/mo average = $14,950/mo = **$179,400/year**
- Plus add-ons: ~$50/agency/mo = $2,500/mo additional
- **Year 2 total: ~$210,000**

### Aggressive (Year 3, FMO partnership)
- 1 FMO with 200 agencies × $199/mo (bulk rate) = $39,800/mo = **$477,600/year**
- Plus direct agencies: 100 × $299/mo = $29,900/mo = $358,800/year
- **Year 3 total: ~$836,000**

---

## 11. Tim's Role in the White Label Business

- **Founder/CTO:** Product vision, technical architecture, carrier parser maintenance
- **Initial sales:** Medicare agent community relationships
- **Support:** Could hire a VA for tier-1 support once at 20+ agencies
- **Ongoing development:** 10-15 hrs/week once core product is stable

This is a lifestyle business at the low end, a legitimate SaaS company at the high end. Either way it justifies Tim's technical investment and positions him as the infrastructure layer for Medicare insurance agencies.

---

*This document is confidential. Founders Insurance Agency is the testing ground and first customer.*
*White label launch target: Q1 2027 (after Founders deployment is stable and proven)*
