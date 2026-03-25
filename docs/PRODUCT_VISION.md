# Medicare Agency Management System (MAMS)
## Product Vision — White Label SaaS
*Started: March 2026 · Testing ground: Founders Insurance Agency, Charlotte NC*

---

## 1. The Problem

Medicare insurance agencies are running their businesses on a patchwork of 8-15 disconnected tools — generic CRMs, personal cell phones, carrier portals, spreadsheets, and paper. None of these tools were built for Medicare agents specifically, and the result is:

- **Commission errors go undetected** — agents have no way to verify AJ's split math
- **Customers fall through cracks** — a customer can call, text, email, and leave a voicemail with zero cross-channel tracking
- **Data lives in silos** — carrier portals, CRMs, spreadsheets, and phone call logs are completely disconnected
- **AEP is chaos** — agents work 10-hour days back-to-back with no automation, customers feel ignored
- **Cannibalization goes unchecked** — agents write customers without knowing if another agent already owns them
- **Compliance is manual** — SOA tracking, 10-year document storage, CMS-compliant communications are all handled ad hoc

The tools that exist (Zoho, HubSpot, AgencyZoom) were built for software salespeople. They don't understand MBI, carrier BOB exports, commission splits, AOR ownership, Medicaid levels, D-SNP eligibility, or the 48-hour SOA rule.

---

## 2. The Solution

**A purpose-built Medicare Agency Management System that consolidates the entire agent tech stack into one platform.**

Built by a Medicare agent, for Medicare agents. Every feature exists because a real agent needed it. The goal is simple: agents open one tab, and everything they need is there. No switching between Zoho, carrier portals, spreadsheets, Calendly, and MedicareCenter.

### What makes it different from every other CRM:

| Feature | MAMS | Zoho | AgencyZoom | HubSpot |
|---|---|---|---|---|
| Carrier BOB auto-import | ✅ 6 carriers | ❌ | Partial | ❌ |
| Commission audit (split verification) | ✅ To the penny | ❌ | ❌ | ❌ |
| AOR history + cannibalization detection | ✅ | ❌ | Partial | ❌ |
| MBI-based customer master | ✅ | ❌ | ❌ | ❌ |
| Medicaid level + D-SNP eligibility | ✅ | ❌ | ❌ | ❌ |
| Partner pharmacy tracking | ✅ | ❌ | ❌ | ❌ |
| SOA management (CMS-compliant) | ✅ | ❌ | Partial | ❌ |
| MedicareCenter PDF OCR → customer match | ✅ | ❌ | ❌ | ❌ |
| NIPR license status sync | ✅ | ❌ | ❌ | ❌ |
| AEP communication automation | ✅ | Manual | Manual | Manual |
| CMS Plan Finder API integration | ✅ | ❌ | ❌ | ❌ |

---

## 3. The Name

Working name: **MAMS** (Medicare Agency Management System) — functional but not a brand.

### Name candidates:
| Name | Vibe | Notes |
|---|---|---|
| **MedicareOS** | Bold, descriptive | Positions as an operating system, not just a CRM |
| **AgentCore** | Professional, agent-focused | "The core of how you run your agency" |
| **Meridian** | Sophisticated, trustworthy | Non-obvious, premium feel |
| **PlanIQ** | Intelligence angle | Good for the analytics features |
| **AnchorCRM** | Stability, trust | Good but has "CRM" which undersells it |
| **MediTrack** | Clean, specific | Risk of confusion with medical records |
| **Clearpath** | Journey/guidance | Could work for Medicare context |

**Recommendation:** MedicareOS or AgentCore. Both are memorable, clearly describe the product, and work for white label without being tied to any one agency.

---

## 4. Target Market

### Primary: Independent Medicare Insurance Agencies (1-20 agents)
- Estimated 15,000-20,000 such agencies in the US
- Currently using Zoho ($50-300/agent/mo) or worse, spreadsheets
- Key pain points: commission reconciliation, AEP chaos, customer data quality, compliance

### Secondary: FMOs (Field Marketing Organizations)
- FMOs manage networks of hundreds to thousands of agents
- White-label opportunity: FMO brands the platform for their agent network
- Volume licensing: one FMO deal = instant access to their entire network

### Tertiary: Solo Medicare Agents
- Individual practitioners with 50-500 clients
- Lighter version, lower price point ($49-99/mo)
- Gateway to agency tier as they grow

---

## 5. Pricing Model

### Per-Agency SaaS
| Tier | Agents | Price/mo | Annual |
|---|---|---|---|
| Solo | 1 | $99 | $990 |
| Small Agency | 2-5 | $249 | $2,490 |
| Agency | 6-15 | $499 | $4,990 |
| Enterprise | 15+ | Custom | Custom |

### Add-On Modules
| Module | Price/mo | What It Does |
|---|---|---|
| Communication Hub | $99 | Twilio + Retell AI + Calendly + auto-reply + SMS campaigns |
| Email Campaigns | $49 | SendGrid-powered, CMS-compliant templates, filtered lists |
| SOA Management | $49 | Send, track, e-sign, store SOAs |
| Meet Recording | $29 | Google Meet per-appointment recording + AI summary → customer records |
| NIPR Sync | $19 | Automatic license status + CE renewal tracking |

### Setup Fee
- $500 one-time onboarding per agency
- Includes: data import from existing CRM, carrier parser configuration, 1hr training call

### FMO Bulk Licensing
- $149/agency/mo for networks of 50+ agencies
- White-label branding: $500/mo additional
- FMO revenue share option: 20% of collected subscription revenue

---

## 6. Feature Roadmap (Full Vision)

### ✅ Phase 1 — Core (Built at Founders)
- Carrier BOB import (6 carriers, auto-detection)
- Agent dashboard (per-agent filtered)
- Admin overview (agency-wide KPIs)
- Commission audit (5 carriers, per-agent split rates, contract validation)
- Agent settings (carrier contracts, splits, agent IDs)
- Birthday labels (Avery 5160 PDF)

### 🔜 Phase 2 — Customer Master (Next)
- Customer master database (MBI linking, editable records)
- Agent-editable records (carrier data preserved, agent corrections authoritative)
- Point of contact management (POC ≠ patient — daughter, nurse case manager, etc.)
- AOR ownership history (full timeline per customer)
- Cannibalization detection (flag when agent writes an existing customer)
- Pharmacy master list + customer tagging
- Medicaid level tagging + D-SNP/C-SNP eligibility logic
- MedicareCenter PDF OCR → auto-match to customer record
- Deal stage pipeline (Lead → SOA Sent → Appointed → Enrolled → Active → Termed)
- Customer profile page (full view — policies, AOR history, contacts, tasks, notes)
- Clickable customer names in commission line items

### Phase 3 — Compliance + Reference
- SOA creation + sending (CMS-compliant, SMS or email)
- SOA e-signature (DocuSign or native)
- 10-year document storage
- MedicareCenter SOA reference integration
- Carrier plan master database (CMS Plan Finder API — H-numbers, premiums, coverage)
- C-SNP qualification reference chart (chronic conditions → eligible plans)
- Medicaid benefit reference tables (income limits, coverage by level, by state)
- NIPR/Sircon license status sync (automatic, per agent)
- Agent profile page (NPN, writing numbers, contract dates, licenses per state)
- Carrier rep contact directory (rep name, phone, email, what they handle)
- CE requirements + renewal tracking per state per license
- Knowledge base (common servicing issues + solutions, searchable)
- Out-of-state contracting requirements reference

### Phase 4 — Communication Hub
- **Twilio** integration (call logs, SMS — replaces RingCentral/VOXO/personal cells)
- **Retell AI** voice engine — inbound missed calls handled by AI; appointment booking mid-call
- **Google Meet** per-appointment recording + AI summary → customer record (replaces Fireflies — eliminated)
- **HealthSherpa** enrollment webhook → customer match → AOR history (replaces MedicareCenter PDF OCR)
- SMS template library (admin-approved, CMS-compliant)
- Email campaign module (SendGrid, filter by carrier/plan/renewal date/birthday/Medicaid level)
- Calendly agency-wide adoption + booking pages per agent
- Automated appointment reminder sequences (day-before + 1-hour SMS/email)
- Post-appointment follow-up automation
- Automated inbound task generator (missed call, SMS → task created + prioritized)
- "Who's calling?" lookup (inbound phone number → customer record instantly)
- Replace Dropbox with Google Drive integration (already paid for via Workspace)

### Phase 5 — Operations + Admin
- Expense reimbursement tracking (stamps, AHIP, CE, etc.)
- Agent onboarding workflow
- SOP documentation hub
- Time tracking per customer (prospecting vs servicing analytics)
- Ticket system for customer servicing issues (open/in-progress/resolved)
- Action items after calls (manual + Retell AI / Google Meet automated)
- Lead source tracking (pharmacy referral, self-generated, web, referral)

### Phase 6 — Analytics + Forecasting
- Commission forecast (Part D + supplement + MAPD rates)
- AEP performance tracking per agent (appointments booked, enrolled, conversion rate)
- Retention rates by carrier and plan
- Churn risk scoring (flag high-risk customers proactively)
- Partner pharmacy ROI (leads generated per pharmacy per rent dollar)
- Year-over-year BOB growth by agent and carrier
- Time spent prospecting vs servicing (ROI per customer)
- Agency revenue dashboard (gross commissions, splits, pharmacy rent, net)

### Phase 7 — Mobile + Customer Portal
- PWA (Progressive Web App) — installs on home screen, works offline for read-only
- Customer portal (customers view their plan, book appointments, see renewal dates)
- SMS/email verification for customer contact info
- Customer-facing SOA signing

### Phase 8 — White Label + Multi-Tenant
- PostgreSQL schema-per-tenant architecture
- Custom branding per agency (logo, colors, agency name)
- Admin portal for MAMS operator (manage agencies, billing, support)
- Stripe billing integration
- Onboarding wizard for new agencies
- Data export (agencies can leave and take all their data)
- FMO bulk provisioning
- API for FMO integrations

---

## 7. Technical Architecture

### Current (Single Tenant — Founders)
```
Flask app → SQLite → One agency
```

### Future (Multi Tenant)
```
PostgreSQL with schema-per-tenant:
  public schema: billing, global carrier plans, system config
  founders_abc schema: all Founders data
  agency_xyz schema: all XYZ Agency data

Benefits:
  - Maximum data isolation (HIPAA-friendly)
  - Easy per-agency backup and restore
  - Clear data ownership for portability
  - Scales to hundreds of agencies on managed PostgreSQL
```

### Infrastructure Scaling
```
1 agency (now):    NixiHost VPS $5/mo
10 agencies:       Same VPS upgraded $20/mo
50 agencies:       DigitalOcean Managed PostgreSQL + App Platform ~$100/mo
200+ agencies:     AWS RDS + ECS, dedicated DevOps
```

### Key Third-Party APIs
| Service | Purpose | Pricing | Priority |
|---|---|---|---|
| CMS Plan Finder API | Auto-populate carrier plan database | Free (government) | High |
| NIPR API | License status + CE tracking | Free (government) | High |
| Twilio API | Call logs, SMS, SIP trunking to Retell AI | Pay-as-you-go (~$22/mo AEP per agent) | **Confirmed** |
| Retell AI API | AI voice engine — inbound missed calls, appointment booking | $0.07/min | **Confirmed** |
| Calendly API | Booking pages, webhooks, mid-call availability check | $10/agent/mo | High |
| Google Meet REST API | Per-appointment recording + Workspace Events webhook | $0 (Workspace Business Plus) | High |
| HealthSherpa API | Enrollment webhooks (replaces MedicareCenter PDF OCR) | Free | High |
| SendGrid API | Email campaigns, transactional | Existing ($20/mo Essentials) | Built |
| Claude API (Haiku 4.5) | Transcript extraction, structured data from calls/meetings | ~$10/AEP season | Medium |
| DocuSign API | SOA e-signature | $10-25/mo | Medium |
| Make.com | Automation (mid-call Calendly check, post-call routing) | Existing subscription | Built |
| Medicare.gov | Drug cost reference (most CMS-compliant) | Free | Medium |

---

## 8. HIPAA Considerations

Customer data includes DOB, Medicare ID, health plan information — this is technically PHI (Protected Health Information).

**Before selling to other agencies:**
- Business Associate Agreement (BAA) with all data processors (hosting, SendGrid, etc.)
- Data encryption at rest and in transit (already have SSL — need DB encryption)
- Access logging (audit_logs table already exists)
- Data retention and deletion policies
- Privacy policy + terms of service
- Consider HIPAA-compliant hosting (AWS GovCloud, or NixiHost BAA)

**Note:** Building for Founders only, the risk is lower. Building for 50 agencies requires proper HIPAA compliance infrastructure.

---

## 9. Competitive Landscape

| Product | Price/mo | Medicare-Specific | Commission Audit | BOB Import | AOR Tracking | Communication |
|---|---|---|---|---|---|---|
| **MAMS** | $99-499 | ✅ Built for it | ✅ Yes | ✅ 6 carriers | ✅ Yes | ✅ Planned |
| Zoho CRM | $50-300/agent | ❌ Generic | ❌ No | ❌ No | ❌ No | Partial |
| AgencyZoom | $149-499 | Partial | ❌ No | ❌ No | Partial | Partial |
| HubSpot | $90-800/agent | ❌ Generic | ❌ No | ❌ No | ❌ No | Partial |
| MedicareCenter | Free-$99 | ✅ Enrollment only | ❌ No | ❌ No | ❌ No | ❌ No |
| Amplicare | $200+/agent | Partial | ❌ No | ❌ No | ❌ No | ❌ No |
| Salesforce | $300+/agent | ❌ Generic | ❌ No | ❌ No | ❌ No | Partial |

**Key insight:** No product in the market does commission audit against carrier statements. The commission audit feature alone pays for itself — one caught discrepancy per year justifies the annual subscription. And no product handles carrier BOB normalization across multiple carriers automatically.

---

## 10. The Origin Story (Marketing Asset)

*"I told the other agents four years ago not to give out their personal cell numbers to customers. They didn't listen. Now every AEP they're drowning in calls to their personal phones, working 10-hour days back-to-back with no time to respond to anyone. Meanwhile I built an automation stack that auto-replied to missed calls, booked appointments automatically, sent reminders, and sent follow-up emails with meeting summaries. I had more appointments and less stress than any other agent in the office. Then I realized — I could build the platform that gives every Medicare agent access to that system, without needing to be technical."*

This is the story that sells. It's real, it's specific, and it highlights a pain point every Medicare agent recognizes.

---

## 11. Go-To-Market Strategy

### Step 1: Founders as living proof (Now → Q3 2026)
- Build and refine with real Founders data
- Document every pain point solved with specific numbers
- "Commission audit caught $X in discrepancies in 3 months"
- "AEP automation booked 40% more appointments with 30% less time"

### Step 2: FMO partnerships (Q4 2026)
- FMOs are the fastest path to scale — one deal = access to their entire agent network
- Target small-to-mid FMOs (50-500 agents) who are frustrated with their current tools
- Offer a 90-day free pilot for FMO's top 10 agents

### Step 3: Medicare agent communities (Q1 2027)
- Facebook groups (Medicare Insurance Agents has 50K+ members)
- NABIP membership and events
- YouTube content: "How I automated my Medicare practice"
- LinkedIn targeting insurance agency owners in Medicare-heavy markets

### Step 4: Content marketing (Ongoing)
- Tim as the face: "The agent who built his own CRM because nothing else worked"
- Tutorials on carrier BOB normalization, commission verification, AEP automation
- Positions MAMS as the authoritative tool in the space

---

## 12. Revenue Projections

### Year 1 (Post-Launch, Conservative)
- 10 agencies × $249/mo = $2,490/mo → **$29,880/yr**
- Setup fees: 10 × $500 = $5,000
- **Year 1 Total: ~$35,000**

### Year 2 (Moderate Growth)
- 50 agencies × $299/mo avg = $14,950/mo
- Add-ons: ~$50/agency avg = $2,500/mo
- **Year 2 Total: ~$210,000**

### Year 3 (FMO Partnership)
- 1 FMO × 200 agencies × $199/mo (bulk) = $39,800/mo
- Direct agencies: 100 × $299/mo = $29,900/mo
- **Year 3 Total: ~$836,000**

### Break-Even Analysis
- VPS + SendGrid + third-party APIs at scale: ~$500/mo
- Break-even: 3 Small Agency subscriptions ($249/mo × 3 = $747/mo)
- At 10 agencies: ~$2,500/mo profit after infrastructure

---

## 13. Tim's Role

- **Founder / CTO:** Product vision, technical architecture, carrier parser maintenance
- **Domain Expert:** 8 years Medicare insurance — knows every edge case
- **Initial Sales:** Medicare agent community relationships
- **Support:** VA for tier-1 support once 20+ agencies
- **Time Investment:** 10-15 hrs/week once core product is stable at Founders

This works as a lifestyle business at 10 agencies ($2,500/mo passive) or a real company at 100+ agencies ($30K+/mo). Either outcome is a win given the existing investment.

---

## 14. Legal and Compliance Checklist (Before White Label)

- [ ] HIPAA BAA with all data processors
- [ ] Database encryption at rest
- [ ] Privacy policy + terms of service
- [ ] Data export capability (customers can leave)
- [ ] SOC 2 (eventually, required by larger agencies)
- [ ] Tech E&O insurance as a software vendor
- [ ] CMS compliance review of any SOA or marketing templates
- [ ] State-specific insurance data handling requirements
- [ ] Stripe or similar for PCI-compliant billing

---

*This document is confidential.*
*Founders Insurance Agency is the testing ground and first customer.*
*White label launch target: Q1 2027*
*See FOUNDERS_PORTAL_CONTEXT.md for current build status and technical details.*
