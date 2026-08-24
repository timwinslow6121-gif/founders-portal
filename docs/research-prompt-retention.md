# Research prompt — proactive retention for Medicare agencies

Paste the block below into Perplexity (or Claude/GPT with web search). Notes on why
it's shaped this way follow at the end.

---

## THE PROMPT

> I am a licensed Medicare insurance agent at a 6-agent independent agency in
> Charlotte / Kannapolis, North Carolina. We service roughly 5,600 active Medicare
> Advantage, Part D and Medigap policies. I am building an internal CRM/portal for
> the agency and need evidence-based guidance on client retention and proactive
> communication.
>
> **My core problem:** our client support is almost entirely *reactive*. We wait for
> customers to call us with a problem instead of reaching them before the problem
> reaches them. Two real examples from my book:
>
> 1. In 2025, CEENTA (a large Charlotte ENT/eye practice) went out of network with
>    UnitedHealthcare for 3–4 months during a contract dispute. We fielded calls and
>    appointments about it constantly, one customer at a time, because we never
>    proactively told anyone.
> 2. UHC and Tryon Medical Partners are in contract negotiations now, expiring
>    1 Oct 2026. Both sides expect to settle — as they usually do — but customers are
>    calling me alarmed that their doctor is about to be out of network. A single
>    well-worded message to the affected customers would prevent most of those calls.
>
> Today we touch each customer about **four times a year**, all one-way physical mail:
> a birthday card, an AEP letter, an ANOC notice, a renewal notice. None of them
> carry a way to reply. We have no email or SMS campaign capability.
>
> **Please research and answer the following. Cite sources and give publication dates;
> flag anything older than ~3 years or not specific to US Medicare.**
>
> **1. Contact frequency and retention.** What does the evidence actually show about
> how often an insurance agent should contact a client to maximize retention and
> loyalty? Distinguish findings specific to Medicare/senior insurance from general
> P&C, life, or B2B marketing research. If a specific number of annual touchpoints is
> commonly cited, identify the original study rather than the blog posts repeating it,
> and say how strong the evidence is.
>
> **2. Content that works vs. content that annoys.** What types of proactive
> touchpoint measurably improve retention with a **65+ Medicare population** —
> educational content, benefit reminders, plan-change alerts, birthday/holiday
> greetings, health/wellness content, newsletters? Which are shown to be ineffective
> or counterproductive? Is there evidence on message length, reading level, tone, or
> personalization for seniors specifically?
>
> **3. Channel preference for seniors.** What does current research say about how
> Medicare-age clients prefer to receive agent communication — physical mail, email,
> SMS, phone, portal? Has SMS adoption among 65+ shifted materially in the last 3–5
> years? Are there differences by age band within the 65+ group (65–74 vs 75+)?
>
> **4. Proactive network-disruption communication.** This is my most specific need.
> When a major provider group goes out of network with a carrier — or is publicly
> negotiating — what is the best practice for an agent to notify affected clients?
> Specifically: How early should you communicate? How do you inform without causing
> panic when the outcome is genuinely uncertain and most disputes settle before the
> deadline? Are there examples, templates, or documented approaches from agencies or
> FMOs? What do carriers themselves recommend or permit agents to say?
>
> **5. CMS marketing compliance — the constraint.** What are the current CMS
> marketing and communication rules governing agent-initiated contact with existing
> Medicare clients? Please distinguish clearly between **"marketing"** (heavily
> regulated) and **"communications"** (less so) under CMS rules, and cover: rules for
> email and SMS to existing clients, consent/opt-in requirements, whether
> plan-specific content triggers marketing-material review, retention requirements for
> communication records, and anything that changed in the CY2025 or CY2026 Final Rule.
> **This constrains everything above — a strategy I cannot legally execute is
> worthless to me.**
>
> **6. Measurement.** What retention metrics do well-run Medicare agencies actually
> track, and what are realistic benchmark figures for annual client retention /
> persistency in Medicare Advantage? How is retention typically measured — policy
> persistency, client count, AEP switching rate?
>
> **Format:** Answer each numbered section separately. Lead each with the practical
> takeaway, then the supporting evidence and citation. Where the research is thin,
> contested, or mostly vendor marketing content, say so plainly rather than
> presenting weak claims as established fact. I would rather know a question is
> unanswered than act on a number nobody verified.

---

## Why the prompt is shaped this way

- **It gives real context.** Book size, state, carrier mix, and two concrete
  incidents. Generic prompts get generic answers; the CEENTA and Tryon cases make
  question 4 answerable in specifics.
- **It separates Medicare from general insurance marketing.** Most "7 touchpoints a
  year!" content is B2B marketing blog filler recycled without a source. Asking for
  the original study filters that out.
- **It puts CMS compliance in scope as a constraint, not an afterthought.** Any
  email/SMS campaign strategy that violates CMS marketing rules is useless. Better to
  learn the boundary before designing the feature.
- **It explicitly licenses "I don't know."** The last paragraph asks the model to
  flag thin or vendor-driven evidence. That is the guard against getting a
  confident-sounding number that turns out to be someone's content marketing — the
  same reason the touchpoint claim was left out of Brian's proposal.

## What to do with the answers

- Anything **well-sourced** on frequency/channel → can support the proposal's
  communications argument, with the citation.
- The **CMS compliance boundaries** → these become real requirements for the portal's
  campaign feature, not nice-to-haves. Capture them before building.
- The **network-disruption playbook** → this is a portal feature in its own right:
  filter the book by carrier + provider group, generate the affected-customer list,
  send one accurate message. The Tryon deadline (1 Oct 2026) is a live test case.

## Related backlog

The Medicare Updates Hub (Phase 1 shipped, `/updates`) already stores carrier intel
tagged to a plan with a live member count. The network-disruption use case is close
to what that hub was built for — an update tagged to affected plans, plus the ability
to *send* rather than just display, is a small step from what exists.
