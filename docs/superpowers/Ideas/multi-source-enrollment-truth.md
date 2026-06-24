# Multi-Source Enrollment Truth — BOB backstop + HealthSherpa events (brainstorm seed)

_Captured 2026-06-24 (Tim). A forward-looking architecture note, NOT a current task. Brainstorm into a real spec when HealthSherpa provisioning lands (see BACKLOG → HealthSherpa blocker)._

## The core idea

The portal's customer/policy/AOR data should be kept fresh + accurate from **multiple
enrollment sources of different fidelity**, with a clear precedence so they reinforce —
not fight — each other. Today we reconstruct enrollments after the fact from monthly
carrier **BOB** snapshots; that's a periodic, lower-fidelity source. **HealthSherpa
(API + webhooks)** would give us **real-time, event-level enrollment truth** — including
the application/signed date, plan, carrier, and agent at the moment of enrollment.

## Why this matters (it solves real gaps we've already hit)

- **The AEP same-effective-date tie-break** (logged 2026-06-24 in the dedup spec): two
  apps for two plans both effective Jan 1 → CMS honors the LAST application submitted.
  BOB doesn't reliably give us submission order; **HealthSherpa events carry the app/
  signed date** — the exact tie-break datum. A real-time event stream makes "last app
  wins" trivially correct instead of a reconstruction problem.
- **Freshness**: events arrive when the enrollment happens, not weeks later in a BOB pull.
  Feeds the AOR timeline (open a new interval / close the old) at the right moment.
- **Provenance**: a HealthSherpa-sourced fact is higher-trust than a BOB-derived one —
  fits the existing provenance precedence pattern (agent-fix > event > BOB > inferred).

## The critical constraint — HealthSherpa is SUPPLEMENTARY, never a replacement

BOB (the carrier's OWN record) must remain the **universal backstop**, because
HealthSherpa structurally cannot see everything:

1. **Not every agent uses HealthSherpa** for Medicare — some enroll through other tools or
   the carrier portal. Their enrollments never touch HealthSherpa.
2. **Carrier plan suppression**: some carriers only permit enrollment on **their own agent
   portal** and block third-party platforms (HealthSherpa, MedicareCenter) entirely. Those
   enrollments will NEVER flow through HealthSherpa — BOB is the only way we learn about
   them.

So the model is **complementary, not either/or**:
- **HealthSherpa events** = high-fidelity, real-time, where available (carries app date).
- **BOB** = universal coverage backstop, catches everyone incl. suppressed-plan/portal-only
  enrollments + non-HealthSherpa agents.
- Reconcile the two (a HealthSherpa event should match + enrich a later BOB row, not
  duplicate it — key on MBI/member_id + carrier + effective date).

## Adjacent sources (same pattern)

- **MedicareCenter** — same third-party-suppression caveat as HealthSherpa; a BOB-style
  enrollment PDF source (already noted in Phase 5 backlog as OCR-able). Lower fidelity than
  a live API.
- The carrier **commission ledger** is yet another after-the-fact signal (who got paid).

## When to brainstorm this into a spec

Trigger: **HealthSherpa agency account is provisioned** (webhook URL registered +
`HEALTHSHERPA_WEBHOOK_SECRET` in .env — see BACKLOG → external blockers / Phase 3.06).
The Phase 3.06 code (`comms/` webhooks) was scaffolded for exactly this. At that point:
a HealthSherpa enrollment-event ingest that (a) opens/closes AOR intervals in real time,
(b) carries the app/signed date (→ the AEP tie-break), (c) reconciles against BOB without
duplicating, (d) records provenance = "healthsherpa_event" (higher trust than BOB).

## Related
- `docs/superpowers/specs/2026-06-24-chronological-bob-dedup-design.md` — the AEP tie-break gap this would solve.
- `docs/superpowers/Ideas/SESSION-NOTES-commission-customer-sync.md` — the unified-pipeline / stub / provenance decisions this extends.
- The shipped §6b term→close-open-AOR lifecycle + §4.2 plan-history timeline (2026-06-23) = the AOR substrate HealthSherpa events would feed in real time.
