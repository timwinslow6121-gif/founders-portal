# AEP 2025 call data — ANALYZED

**Status:** ✅ done. Source: `docs/CallLog_20260819-202751.csv` (780 records,
Sep 1 – Dec 31 2025). Figures below are in the one-pager.

---

## Headline findings — AEP window (Oct 1 – Dec 7 2025)

| | |
|---|---|
| Calls in the window | **617** |
| Unanswered (missed / voicemail / caller hung up) | **310** |
| Answered | 302 |
| **Share unanswered** | **51%** |
| Active days with call traffic | 57 of 68 |
| Unanswered per active day | **5.4** |
| Distinct people missed | 165 |
| **People missed MORE THAN ONCE** | **66 (40%)** |
| Failed attempts to those 66 | **211** |
| Worst single number | **13 attempts** before connecting |
| Average answered call | 9.6 min |
| Total talk time in window | 54.2 hrs (≈57 min/day) |

**Callback cost at the observed 9.6-min average:** 310 × 9.6 min ≈ **50 hours** ≈
5.5 nine-hour days ≈ **99 thirty-minute appointment slots.**

Data is essentially complete — only 3 Mon–Sat days in the window have zero logged
calls, and two of those are Thanksgiving and the Saturday after.

---

## ⚠ IMPORTANT — a correction to what we assumed

The working assumption was **"20+ missed calls per day."** The actual figure is
**5.4 per active day.** Do not use 20+ — your own log contradicts it, and a number
Brian can disprove costs more than it gains.

**The real data is still strong — it's just a different argument.** The power isn't
raw volume, it's:

1. **51% of calls went unanswered.** Half of everyone who reached out got nobody.
2. **40% had to be missed repeatedly** — 66 people, 211 failed attempts, one tried
   13 times. That's the phone-tag point, evidenced.
3. **You had the best system and the smallest book and this still happened.**

Volume was never the persuasive part. *A coin-flip chance of reaching your agent
during the only nine weeks that matter* is the persuasive part.

---

## ⚠ 51% IS A FLOOR, NOT A MEASUREMENT — this is in the proposal

The log covers **one channel**: the VOIP line. It does **not** include:

- calls to/from **personal cell phones** (Tim's or the customer's)
- calls to/from the **pharmacy number**, where staff took messages for agents
- **any SMS**, in either direction (the export is voice-only — `Type` = "Voice" on
  all 780 rows)

So every unanswered call that reached Tim another way is invisible here. **The real
miss rate is higher than 51%.**

This makes the number *stronger*, not weaker, and the document now says so
explicitly. A measured floor is harder to argue with than an estimate — Brian can
question an assumption, but "it's at least this bad, on the only channel that kept
records" has no soft edge to push on.

---

## ⬜ OPEN — the SMS-to-booking conversion (worth chasing, not blocking)

Tim's VOIP auto-texted a Calendly link to anyone who left a voicemail. **How many of
those booked themselves an appointment?** That is the closest thing to direct proof
that the portal's core mechanic works, because the auto-text is a crude version of
exactly what the portal would do at scale: reach the customer first, let them
self-select, and keep the appointment slot for someone who needs it.

**Where to look:** Calendly, not the phone system. Export bookings for Oct 1 – Dec 7
2025 and segment by source/UTM if the link carried one; otherwise compare booking
timestamps against voicemail timestamps in this log (a booking within ~24h of a
voicemail from the same person is almost certainly the auto-text working).

**A weak proxy already in this data — do NOT use it as evidence:** of 122 numbers
that left a voicemail, 71 (58%) never called again, while 51 (42%) had to keep
trying. "Stopped calling" is ambiguous — it could mean booked, gave up, or reached
Tim on a personal cell. It hints the auto-text helped, but it cannot carry that
claim. Calendly is the only real source.

---

## Secondary findings (useful in conversation, not in the document)

- **Timing:** 92% of unanswered calls arrive inside 9am–6pm — i.e. during
  appointments. Only 8% are after-hours. So the problem isn't customers calling at
  odd times; it's that **you're with another customer**. That's exactly the gap a
  support system fills, and it's why Brian doesn't experience it.
- **Peak days:** 14 unanswered on Mon 10/06; 11 on Mon 11/03, Wed 11/12, Mon 12/01.
  Mondays are consistently worst.
- **Trend:** October 43% unanswered → November 58% → December 53%. **It got worse as
  the season went on**, which is what you'd expect as backlog compounds.
- **Volume shape:** 293 calls in October, 232 in November, 92 in the first week of
  December.

---

## The line for the room (not the document)

> "Half the people who called me during AEP got nobody. Not because I was ignoring
> them — because I was sitting with another customer. And 66 of them had to try more
> than once; one called 13 times. I had the only real phone system in the agency and
> the smallest book. Ask Chris or Justin what theirs looked like."

Handing Brian a question he can verify himself lands harder than a claim he has to
accept.

---

## Reproducing this

```bash
cd docs && python3 - <<'PY'
import csv, collections
from datetime import datetime
rows=list(csv.DictReader(open('CallLog_20260819-202751.csv',encoding='utf-8-sig')))
def d(r): return datetime.strptime(r["Date"].split()[1],"%m/%d/%Y").date()
aep=[r for r in rows if datetime(2025,10,1).date() <= d(r) <= datetime(2025,12,7).date()]
UN={"Missed","Voicemail","Hang Up"}
un=[r for r in aep if r["Action Result"] in UN]
an=[r for r in aep if r["Action Result"] in ("Accepted","Call connected")]
byn=collections.Counter(r["Phone Number"] for r in un)
multi={k:v for k,v in byn.items() if v>1}
print(f"{len(aep)} calls, {len(un)} unanswered = {len(un)/(len(un)+len(an))*100:.0f}%")
print(f"{len(multi)}/{len(byn)} missed more than once; worst {max(byn.values())} attempts")
PY
```

**Note on method:** "unanswered" = `Missed` + `Voicemail` + `Hang Up`. The
`Result Description` column confirms direction — "The *caller* hung up before the
call was answered" is inbound, "The number *you dialed*" is outbound.
