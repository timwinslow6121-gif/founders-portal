# AEP Letter Generator — Design Spec

**Status:** Draft — brainstormed & validated 2026-07-10 (letter design confirmed against a real one-page PDF; send-flow confirmed via interactive mockups). Ready for user review → implementation plan.

**Author context:** Founders Insurance Agency portal. Solo dev (Tim). Grounding artifacts read during design: the 6 real 2025 Cannon/Founders AEP letters (`docs/AEP Letters/`), the real Founders logo + Cannon triangle footer (extracted from those files), and the existing `app/labels.py` (birthday-label PDF) which this feature's address/dedup logic extends.

---

## 1. Problem & Goal

Each AEP (Oct 15 – Dec 7), Founders agents mail **thousands** of plan-specific letters to their customers. Today this is brutal manual labor: organize the BOB by carrier+plan, hand-analyze each plan's ANOC into a "key changes" box, print at a shop, fold, stuff, label, postmark, and drop off — while making sure each customer gets the **correct** letter and no one gets two. Brian has Cannon's staff for this; most agents rely on spouses/pharmacy staff (sometimes paid).

**Goal:** an agent picks their suggested mailings, reviews the recipient list, and clicks send — and a pay-per-piece print-and-mail vendor prints, folds, stuffs, addresses, postmarks, and mails every letter. Personalized per agent (headshot/phone/QR) automatically. The hard back-end is invisible; the agent experience is three screens.

**Non-goals (this spec):** live CMS/ANOC API ingestion (the changes box is hand-authored — human expertise, see §4.1); auto-generating letter copy; bulk customer email (this is physical mail only); a general campaign/marketing engine beyond AEP letters.

---

## 2. Key Decisions (locked during brainstorming)

1. **Vendor = a HIGH-VOLUME bulk mailing house with pay-per-piece pricing, NO monthly subscription, and NO per-month volume cap** (behind a swappable `MailVendor` interface). All-in per-piece **includes postage** (presorted, cheaper than retail stamps) + paper + printing + folding + envelope + insertion + mailing. Founders' volume is **seasonal and spiky**: ~5,000 own-book letters + potentially 2,000–10,000 per pharmacy × ~8 partner pharmacies → **tens of thousands of pieces concentrated in Oct–Dec, ~zero the rest of the year**. This profile REJECTS the low-volume transactional APIs:
   - **Lob — REJECTED:** ~$550/mo subscription floor.
   - **PostGrid — REJECTED as primary:** its "no-commitment" pay-as-you-go tier **caps at 500 mailings/month** (overage fees / forced upgrade beyond that) — a low-volume tier, not a bulk one.
   - **Postalytics:** Free tier $1.42/piece all-in, no minimum — viable but subscription tiers only pay off at high *monthly* volume (not our seasonal pattern).

   **Leading candidates (built for 1 → tens of thousands/millions of pieces, no minimum, no monthly fee, no cap, API-driven, postage included):**
   - **LetterStream** — no monthly fee, no minimum, no cap; first-class letters ~$1.23 each all-in; API. Best profile match.
   - **PCM Integrations** — no setup/monthly minimums, pay-per-piece, national print network "scales to millions/month," batch API.

   Note: at ~30k seasonal pieces the **per-piece rate dominates** any platform fee, so the final pick is a **procurement decision** (get real per-piece quotes from LetterStream + PCM for Founders' volume) — NOT an architecture decision. The interface is vendor-agnostic; the chosen vendor is one adapter. See §6.
2. **Letter authoring = constrained fields → guaranteed one page.** Not a free rich-text blob. Brian/AJ fill labeled boxes with character budgets; the sum of budgets is calibrated to fit one 8.5×11 page with locked header + footer. Live char counters + preview. (Validated: a real reportlab one-page render fits with headroom — `docs/AEP Letters/SAMPLE_Modern_AEP_Letter.pdf`.)
3. **Two letter styles:** **Classic** (Brian's serif design, faithfully recreated) and **Modern** (research-backed redesign — see §4.3). Both selectable per template.
4. **Campaign = per-year plan→letter map, authored once by Brian/AJ.** The anti-disaster spine: because recipients are gathered **by plan**, a customer can land in exactly one BOB bundle → "same person got two different letters" becomes structurally impossible.
5. **Agents don't author, they send.** Compliance gate (Option B) = **template content is approved once by Brian/AJ** (content + disclaimer locked); agents then send approved letters to their own customers freely. Agents only ever supply merge fields (name/phone/headshot), never letter copy.
6. **Identity/audience has two sources:** BOB (plan-driven, per-agent, household-deduped) OR an **ephemeral imported CSV** (pharmacy blast; not persisted; may overlap the agent's own book by design).
7. **Brand = a property of the template** (locked header + footer asset): `founders`, `cannon`, `plain`, `pharmacy_voice`, extensible. Footer/disclaimer blocks are **admin-editable** assets (so the TPMO/CMS wording is Brian's to fix, not hard-coded).
8. **Personalization is a template flag:** BOB letters personalize per-AOR (the customer's agent's headshot/phone/QR); a pharmacy-voice letter can feature one designated onsite agent instead.
9. **Household de-dupe:** within a **single** mailing, recipients sharing the **same mailing address AND the same plan** collapse to **one** letter (addressed to both). Spouses on **different** plans each get their own letter from their plan's mailing. De-dupe NEVER collapses across different letters.
10. **Send-flow = a 3-page wizard** (each step a full page, one primary button, progress rail). Screen 2 supports **per-row deselect** (+ optional reason) and **inline address fix that writes back to the customer record**.
11. **Portal screens use the real Founders theme** (Plus Jakarta Sans + Merriweather, `var(--gold)`/`--green`/`--surface` tokens, `.card`/`.badge`/`.btn`/`.data-table`, light+dark, focus rings). The printed **letter** follows its own brand-asset design (logo + footer + color-coded changes), which is separate from the portal UI.

---

## 3. Data Model (new tables + one column touch)

All tables carry `agency_id` (non-nullable, scoped on every query) per the multi-tenant rule.

### 3.1 `letter_template`
The authored, approved letter. One row per letter per year.
- `id`, `agency_id`
- `name` (e.g. "UHC MAPD AEP 2026"), `year` (int), `carrier` (nullable — pharmacy blasts may be carrier-agnostic)
- `style` ∈ {`classic`, `modern`}
- `brand` ∈ {`founders`, `cannon`, `plain`, `pharmacy_voice`} (FK to `letter_brand`)
- `personalization` ∈ {`per_aor`, `designated_agent`}; `designated_agent_id` (nullable FK User)
- **Constrained content fields** (each with a max-length enforced in the form AND the model): `title`, `greeting`, `recommendation`, `closing`. Plus `change_items` = JSON list of `{severity: negative|neutral|positive, text}` (max N items, each max M chars). Severity drives the red-▲ / yellow-▬ / green-● marker (shape+color redundancy for B/W + colorblind).
- `status` ∈ {`draft`, `approved`}; `approved_by_id`, `approved_at`
- `created_by_id`, timestamps
- **Invariant:** an agent may only send a template whose `status='approved'`. The locked header/footer/disclaimer are NOT stored here (they come from `brand`), so they can't be edited per-letter.

### 3.2 `letter_brand`
Admin-editable locked header + footer/disclaimer assets.
- `id`, `agency_id`, `key` (`founders`/`cannon`/`plain`/`pharmacy_voice`/…), `display_name`
- `header_asset` (image ref, e.g. Founders logo), `footer_asset` (image ref, e.g. Cannon triangle band)
- `disclaimer_text` (the CMS/TPMO block — **admin-editable**; exact 2026 wording is a Brian/compliance-confirmed value, see §8)
- Adding a brand = one new row + its assets; no code change.

### 3.3 `aep_campaign` + `aep_campaign_bundle`
The per-year plan→letter map (authored by Brian/AJ once).
- `aep_campaign`: `id`, `agency_id`, `year`, `name`, `status` (`draft`/`active`), timestamps.
- `aep_campaign_bundle`: `id`, `campaign_id`, `label` (plain-language "WHO", e.g. "UHC MAPD customers"), `template_id` (the letter), `plan_ids` (list of Plan FK — the plans this bundle targets), `send_window` (optional, e.g. "primary" vs "2nd notice").
- Resolving a bundle for an agent = "active policies owned by this agent whose `plan_id ∈ bundle.plan_ids`, with a mailing address."

### 3.4 `mail_batch` + `mail_batch_item`
One agent's actual send (the record Brian sees too).
- `mail_batch`: `id`, `agency_id`, `agent_id`, `campaign_id` (nullable — pharmacy blasts have none), `template_id`, `brand_key`, `status` ∈ {`draft`, `submitted`, `in_production`, `mailed`, `failed`}, `letter_count`, `est_cost_cents`, `vendor` (`lob`), `vendor_batch_ref`, `submitted_at`, timestamps.
- `mail_batch_item`: `id`, `batch_id`, `customer_id` (nullable for imported rows), `recipient_name`, `address1/city/state/zip`, `plan_label`, `included` (bool — deselect), `skip_reason` (nullable), `household_group_ref` (nullable — which combined household), `vendor_piece_ref`, `status`.

### 3.5 Column touch
- `User`: add `headshot_asset`, `scheduling_qr_asset` / `scheduling_url`, `mail_phone` (the phone printed on letters; may differ from login identity). Small additive migration.
- No change to `Customer`/`Policy` schema — address write-back uses existing `Customer.address1/city/state/zip_code` + honors `manually_edited`.

---

## 4. The Letter

### 4.1 The changes box (hand-authored, human expertise)
Each change is `{severity, text}`. Brian/AJ/Tim analyze the ANOCs and hand-pick what matters (e.g. "the medical MOOP looks scary but nobody hits it; the OTC-card-in-store change is what moves people"). Severity → marker: **negative = red ▲**, **neutral = yellow ▬**, **positive = green ●**. **No legend / no explicit "negative" wording** on the printed letter (agents don't openly disparage plans). The marker shape carries meaning even in B/W.

### 4.2 Merge fields (filled at render, per recipient)
`{{customer_first_name}}`, `{{plan_name}}`, and the agent block: `{{agent_name}}`, `{{agent_phone}}`, `{{agent_headshot}}`, `{{agent_qr}}` — resolved from the AOR (per_aor) or the designated agent. Brian never types the agent block.

### 4.3 Two styles
- **Classic** — Brian's design: serif (Georgia-like), centered "Very Important – Please Read", boxed changes, blue recommendation, agent block, brand footer.
- **Modern** — research-backed (senior direct-mail): **sans-serif 12–14pt+**, a benefit **headline with the customer's name** ("Justin, your UHC plan is changing in 2026"), scannable icon bullets, **one high-contrast blue CTA box**, deadline as a visual block, "I read your plan changes for you" framing, warm neighbor voice (no em-dashes, plain-spoken). Keeps Brian's brand footer + color coding + compliance. (Rationale + sources in §9.)

### 4.4 Rendering
Portal renders template + merged data → **PDF** (reportlab, extending the `labels.py` pattern; validated one-page). Header logo + brand footer are full-bleed locked assets; disclaimer is a locked region. PDF is the artifact sent to the vendor.

---

## 5. The Send Flow (3-page wizard)

**Screen 1 — Choose mailings.** Full page. Cards, each = **WHO GETS IT** (plain-language segment name + "N customers in M households") + **THE LETTER** (thumbnail + name + 👁 Preview). Suggested bundles from the active campaign are pre-checked. Status chips (✓ ready / ⚠ N no address). Secondary actions: 🖨 View all mailing labels, + Pharmacy blast (upload CSV). Primary button → review.

**Screen 2 — Review recipients.** Full page. Per-mailing recipient table with:
- **Send checkbox per row** (checked default) → deselect to skip, with optional `skip_reason` ("already met" / "moved" / "deceased" / free text). Live count.
- **Household de-dupe** applied + explained (combined rows show "1 letter (same plan & address)"; different-plan spouse noted).
- **Inline address edit** (✎) — opens street/city/state/zip fields; Save **writes back to `Customer`** (respecting `manually_edited`; sets it true), fixing it for labels + future mailings too. `⚠ no address` rows open editable by default.
- 🖨 print these labels. Primary button → send.

**Screen 3 — Confirm & send.** Full page. Per-mailing counts + total + **estimated mail cost shown up front**. Green "Send N letters for delivery". On submit: create `mail_batch`(+items), render PDFs, hand to the mail-vendor adapter, set `submitted` → poll/webhook to `in_production`/`mailed`. A sent/tracked record (count, cost, expected-in-mailboxes date) visible to the agent AND admins.

---

## 6. Vendor Integration (pluggable, pay-per-piece)

- `app/mail_vendor/` with a `MailVendor` interface: `submit(batch, pdfs, recipients) -> vendor_batch_ref`, `status(ref)`, `estimate(count) -> cents`. **Vendor choice is config, not code** (`MAIL_VENDOR=postgrid|postalytics|...`).
- **High-volume, no-subscription, no-cap bulk mailer only** (Lob + PostGrid rejected, §2 decision 1). Build the adapter for the vendor Founders actually contracts. **LetterStream** (best profile match: no monthly fee, no minimum, no cap, ~$1.23/letter all-in, API to submit PDF + address list) or **PCM Integrations** (pay-per-piece, national print network, batch API). Both are pay-as-you-go and handle tens of thousands of seasonal pieces.
- Config (VPS `.env`): `<VENDOR>_API_KEY`, `MAIL_VENDOR`, `MAIL_FROM_ADDRESS` (return address), `MAIL_PER_PIECE_CENTS` (fallback estimate rate until the live API rate is wired).
- Status updates via the vendor's webhook (signature-verified like existing Quo/Calendly webhooks) OR polling; either updates `mail_batch.status` + item statuses.
- **Cost estimate** shown on Screen 3 uses the live vendor rate if available, else `MAIL_PER_PIECE_CENTS`. Because volume can be tens of thousands seasonally, the estimate must be visible and reasonably accurate before any submit.
- **Test-mode:** vendor test key + a dry-run that renders PDFs and shows the batch without mailing (so agents/Brian preview end-to-end before a live send).
- **Procurement note (business, not code):** get real per-piece quotes from PostGrid + Postalytics for Founders' actual seasonal volume (~5k own book + pharmacy blasts); at ~30k pieces the per-piece rate dominates any seasonal platform fee, so compare on total-season cost. This does not gate the build — the interface is vendor-neutral and the adapter is a thin, late phase.

---

## 7. Roles, Compliance & Safeguards

- **Admin (Brian/AJ):** author + approve `letter_template`s; edit `letter_brand` assets/disclaimer; build the `aep_campaign` plan→letter map; see all batches + agency spend.
- **Agent:** see own suggested mailings; deselect/fix addresses; send approved letters to own customers; upload a pharmacy CSV blast; see own batches.
- **Compliance gate (Option B):** only `approved` templates are sendable; disclaimer + header/footer are locked (brand-level, un-removable); agents can't alter copy.
- **Spend visibility:** cost shown before send; batches record `est_cost_cents`. (A per-batch spend cap requiring admin override is an OPEN option — §8.)
- **Address write-back** honors `manually_edited` and is audited (`log_event`).
- **Agency scoping** on every query; agents restricted to their own AOR customers (reuse `customers.py` `_is_current_aor` / `_customer_query`).

---

## 8. Open Items (confirm before / during build — NOT blockers to planning)

1. **TPMO/CMS disclaimer wording (2026 final rule).** The mechanism (locked, admin-editable `disclaimer_text` per brand) is built now; the exact text is a value Brian/compliance supplies. The rules changed for 2025/2026 (TPMO recording + standardized disclaimer scope). Deferred by Tim; do not invent text.
2. **CMS material-ID / filing status** of each template — confirm with whoever owns Founders' compliance before the first LIVE send. (Checkbox for Brian, not code.)
3. **Spend cap / admin approval of large sends** — decide whether a batch over $X needs admin override, or whether agent self-send (per Option B) is sufficient. Default in this spec: self-send, cost shown.
4. **Marketing vs "educational" classification** — letters citing specific benefit/cost-sharing changes are very likely CMS "marketing" regardless of framing; the Option-B gate handles this by locking approved content + disclaimer. Confirm with compliance.
5. **Character budgets** for the constrained fields need one round of visual tuning against real renders (the preview supports this).

---

## 9. Research basis for the Modern style (why it's worth offering)

Senior direct-mail is a measurable channel: Medicare letters run **~3–6% response** (vs ~0.5% digital); **85%** of people read physical mail; seniors spend **~7 min/day** sorting mail; a letter lives in the home ~17 days. Senior readability research is unanimous on **14–18pt sans-serif, high contrast, generous spacing** — Brian's Classic is ~11pt serif, so Modern's biggest single win is legibility. Other pro tactics baked into Modern: a benefit headline (not a generic red "IMPORTANT"), name personalization, ONE high-contrast CTA, a scannable checklist, deadline as a visual object. **We keep everything Brian owns** (brand footer, color coding, disclaimer, QR, one page) — Modern is an option, not a replacement (Brian's design earned 3× the book; we respect that). Sources: Who's Mailing What (Medicare direct mail), Hallmark Business (MA member engagement), Discovery Eye Foundation + Age-Friendly DC (print design for older adults), SG360.

---

## 10. Build Sequencing (for the implementation plan)

Rough phase order (details → writing-plans):
1. **Data model + migrations** (`letter_template`, `letter_brand`, `aep_campaign`(+bundle), `mail_batch`(+item), User asset columns).
2. **Brand assets + template authoring** (constrained-field form w/ char budgets + live preview; approve workflow) — admin-only.
3. **Letter render engine** (reportlab, Classic + Modern; merge fields; brand header/footer + locked disclaimer; one-page guarantee) — reuse/extend `labels.py`.
4. **Campaign builder** (plan→letter map) — admin-only.
5. **Agent send wizard** (3 screens; bundle resolution; household de-dupe; per-row deselect; inline address write-back; label print) — reuse `labels.py` address logic + Founders theme.
6. **Mail-vendor adapter** (LetterStream/PCM or the chosen bulk pay-per-piece vendor: submit/status/estimate; test-mode; webhook) behind the `MailVendor` interface.
7. **Batch tracking / admin spend view** + audit.
8. **Pharmacy blast** (ephemeral CSV import audience: all-aged or plan-targeted).

Each phase = its own tested slice; the whole feature gets an opus whole-branch review before deploy (money + external-send path). Household de-dupe, address write-back, and the mail-vendor submit path each warrant real-data verification.
