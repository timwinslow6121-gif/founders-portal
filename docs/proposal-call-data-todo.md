# AEP call data — what to pull, and why it matters

**Status:** outstanding. Tim has VOIP data from AEP 2025 somewhere; this is the guide
for what to extract and where it goes in the proposal.

---

## Why this is the most valuable evidence in the proposal

Everything else in the one-pager is **projection**. The triage-minutes, the utilization
rate, the share of customers who need an appointment — all estimates, and all
attackable. Brian can say "8 minutes a call seems high" and the comparison wobbles.

**This is measured data from a real AEP.** He cannot argue with call logs.

And it carries an argument nothing else does:

> Tim had the **best** inbound setup of anyone at Founders — a VOIP system that
> auto-replied by SMS with a calendar link — and the **smallest book**, so the
> lowest call volume of any producing agent. He still got buried.
>
> Every other agent ran AEP on a personal cell phone or through pharmacy staff
> taking messages, with a bigger book generating more calls.
>
> **If it overwhelmed the best-equipped agent with the least volume, it was worse
> for everyone else.** That conclusion needs no estimate — it follows from the data.

That is the emotional core of the pitch, and unlike the rest of it, it is unarguable.

---

## What to pull

**Primary (any one of these makes the case):**

1. **Missed / unanswered inbound calls per day** across Oct 1 – Dec 7 2025.
   The single best number. A daily average plus the peak day.
2. **Total inbound call volume** over the same window — establishes the baseline
   ("this is what the SMALLEST book generates").
3. **Outbound callbacks placed** — the return-call burden.

**Secondary (multiplies the impact):**

4. **Callback connect rate** — what share of return calls actually reached the person.
   Anything under ~50% proves the phone-tag point with your own data.
5. **Call duration** — average inbound and average callback. Turns call counts into hours.
6. **Time-of-day distribution** — if callbacks cluster after 6pm, that's the "hours
   after appointments are done" point, evidenced.
7. **How many SMS auto-replies converted to a booked appointment** — this is the
   closest thing you have to a *proof the portal's approach works*, because the
   auto-reply is a primitive version of exactly what the portal would do at scale.

---

## What the numbers would mean

Callback burden over 52 AEP working days, at 6 minutes per callback:

| Missed calls/day | Per day | Over the season | In 30-min appointment slots |
|---|---|---|---|
| 10 | 1.0 hr | 52 hrs (≈6 nine-hour days) | **104 slots** |
| 15 | 1.5 hr | 78 hrs (≈9 days) | **156 slots** |
| 20 | 2.0 hr | 104 hrs (≈12 days) | **208 slots** |

Against a realistic season of ~500 appointments per agent, 20 missed calls a day is
**over 40% of capacity** spent on callbacks — and that is the floor, because it counts
each callback once and ignores phone tag entirely.

⚠ **Use your real average, not the top of the range.** A defensible 12 is worth more
than an arguable 20. Also confirm the 6-minute callback assumption against your actual
call durations — if you have the data, use it rather than the estimate.

---

## Where it goes in the one-pager

Replace the **"AEP 2026 — as things stand"** panel (currently `~12 days`, built on my
triage estimate) with the real figure. Suggested shape:

> **AEP 2025 — what actually happened**
>
> I ran AEP on a VOIP system that auto-replied to every missed call with a booking
> link. No other agent had that — they used a personal cell or the pharmacy took
> messages. I also have the smallest book, so the fewest calls.
>
> **[N] missed calls a day. Every day of AEP.**
>
> That is [X] hours of callbacks over the season — [Y] appointment slots — and it does
> not count the ones who didn't pick up when I called back. The agents with bigger
> books and no system had it worse. That is where the capacity goes.

Then the green panel's contrast stays as-is.

---

## The line to say out loud in the meeting

Not in the document — for the conversation:

> "I had the best phone setup in the agency and the smallest book, and I still missed
> [N] calls a day for nine straight weeks. Ask Chris or Justin what theirs looked like."

Handing the comparison to Brian as a question he can go verify is stronger than
asserting it — and per *Never Split the Difference*, a question he answers himself
lands harder than a claim he has to accept.
