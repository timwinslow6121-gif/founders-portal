# Session Notes — Commission→Customer Sync (paused 2026-06-03 evening)

Paused mid-brainstorm. AJ is providing **raw, unaltered commission source files tomorrow**.
The files reviewed tonight (`docs/Commission DL/Commission docs/`) were **agent-cleaned/filtered**
— different formatting even within the same carrier — so they are NOT a valid basis to build the
parser. Resume once raw data arrives.

---

## The bug that started this
Uploading commission files (Admin@, for Mike/Justin/Chris/Brian/Anj) creates `CommissionStatement`
+ `PolicyPayment` rows but **never creates `Customer` records**. `commission/routes.py` and
`payments.py` only parse "customer name" as a column — they never write the `Customer` model. So
those agents' books are invisible in the customer database.

---

## Decisions LOCKED tonight (don't re-litigate)

1. **Unified pipeline:** each BoB/commission row = both a payment fact AND a customer/AOR fact,
   created in one pass/transaction. Guarantees "every payment has a customer." Commission sync is
   the **producer** of AOR-interval data that the (paused) customer-access model will **consume** —
   so sync is correctly sequenced first.

2. **Stub customers:** unmatched rows create `Customer(stub=True, source='commission_import')` with
   whatever the file has (name, MBI/carrier-id, agent=AOR, eff/disenroll dates). Visibly marked
   incomplete; auto-promote when BOB import or agent edit fills the gaps. (Matches CLAUDE.md planned
   design.)

3. **Idempotency required:** AJ re-uploads corrected files. Create/update must key on a stable
   identifier (MBI, else carrier member ID, else normalized name — the 3-tier match already in
   `PolicyPayment`), and must NOT create duplicates or stack conflicting AOR intervals on re-run.

4. **Dedup by stable ID, never by name.** Proven by the BCBS "Litchfield,Daniel P" vs
   "Litchfield,Daniel P 2" case — same `Customer No 106814188`, mangled name. Name is unreliable.

---

## Row-classification rule (TENTATIVE — re-confirm against raw data)

Each carrier has a different row-type field; map each to a common taxonomy:
- **ENROLLMENT** (BCBS `FY`/`NEW`, Aetna `CMS New=Y`, Devoted `Initial`) → create/confirm customer
  + open AOR interval.
- **RENEWAL** (BCBS `RENEW`, Aetna `CMS New=N`) → confirm existing AOR, record payment.
- **ADJUSTMENT / CHARGEBACK / SUMMARY** (BCBS `ADJUSTMENT`, stray `$` in a name/type column) →
  payment/reconciliation only, NO customer/AOR.
- **Validate identity before creating:** skip rows where a `$` amount sits where a name/type belongs
  (corrupt/summary lines — seen in Devoted: `-47.71` in the Commission Type column).

AOR interval from a row: agent = Writing/Payee agent; `effective_date` opens it; `Disenroll Date` /
`Coverage-To` closes it (NULL = current AOR). A later file showing a different agent for the same
customer+carrier = a NEW interval (the AOR change / "poach"), recorded — not an overwrite.

**Per-carrier row-type vocabulary observed (incomplete — only 3 carriers, cleaned data):**
- BCBS `Group Type`: FY, NEW, RENEW, ADJUSTMENT
- Aetna `CMS New`: Y/N  (+ has MBI in `Medicare Number`)
- Devoted `Commission Type`: "Initial - Not New", … (+ `Disenroll Date`; Devoted member ID, not MBI)
- **TODO tomorrow:** get full vocabulary across ALL carriers (UHC, Aetna, BCBS, Devoted,
  Healthspring, Humana, GTL, Wellable) from the RAW files.

---

## THE HARD PROBLEM — UHC LOA commission splitting (Mike, Betty, Anj)

UHC pays "Founders" a **single lumped amount** (e.g. $630) that combines commission + true-up +
override, with NO breakout on the statement. Splitting agent-share vs agency-share is genuinely
**not computable from the statement alone**. Known facts:
- New-to-Medicare MAPD max ≈ **$694** (NC); renewal ≈ half, split by agent's contracted rate
  (50%–70%).
- New-to-Medicare **override ≈ $125**, all to Founders.
- Everything **prorated by months remaining in the year**.
- The lumped amount rarely matches a clean rate → ambiguous.
- **Only authoritative resolution:** call UHC commissions directly; they'll tell you the split but
  won't put it on the statement.

**Architectural note:** this is the SAME shape as the plan-provenance problem we already built — an
inferred value + confidence + human-override-with-ground-truth. The UHC split should likely reuse
the provenance pattern: store an inferred split (from rates/proration), a confidence level, and let
AJ override with the phone-call truth. Don't try to make the statement compute what it structurally
can't.

---

## Where we paused
Mid-question: confirming the row-classification rule. Next step tomorrow:
1. Get raw files from AJ.
2. Inspect real row-type vocabulary across all carriers.
3. Confirm/adjust the classification rule above.
4. Resume brainstorm → spec → plan.

## Still queued AFTER this
- **Customer-access model** brainstorm (interval-aware access; consumes the AOR data this sync
  produces). Fully explored tonight; decisions captured in conversation. Key settled points:
  full profile access on direct lookup; enumeration limited to own+delegated book; delegation
  (Betty↔Brian) explicit + modeless + attributed; OEP overlap via AOR intervals; design principle
  = simple default + few labeled controls, no hidden modes (tech-averse users behave like PioneerRx).
