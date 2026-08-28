# Medicare Plan First-Look Intelligence System
## Product and Technical Specification for portal.foundersinsuranceagency.com

**Status:** Planning / design  
**Primary application:** `portal.foundersinsuranceagency.com`  
**Current stack:** Custom application with PostgreSQL backend  
**Current development workflow:** Antigravity IDE + Claude Code  
**Primary use case:** Internal Medicare plan research, comparison, reporting, and contract-year change analysis

---

# 1. Purpose

The existing Founders Insurance Agency portal already stores Medicare plan information using CMS Medicare data.

The problem is timing.

CMS data is the authoritative source, but carriers release preliminary **First Look** materials before CMS data is fully published or verified for the new contract year. During this period, agents need access to preliminary plan details for planning, AEP preparation, carrier comparison, and internal training.

The goal is to add a **First Look data layer** to the existing portal without replacing or corrupting the CMS-sourced production data.

The system should support:

- 2026 vs. 2027 plan comparison
- future year-over-year comparisons
- multiple carriers
- MA/MAPD/SNP/PDP products
- carrier-provided preliminary plan data
- CMS-verified plan data
- filtering and search
- printable comparison reports
- plan-change reports
- service-area/county filtering
- community/contributor data entry
- source-document audit trails
- later reconciliation of First Look data against official CMS data

The portal should remain the single application. Do **not** create a separate standalone plan-comparison app unless there is a compelling architectural reason.

---

# 2. Core Data Rule

The canonical plan comparison key is:

```text
contract_year + CMS_code
```

Example:

```text
2027 + H5253-117-000
```

The CMS code should be stored in full Contract-Plan-Segment format whenever available:

```text
H5253-117-000
```

Plan marketing names should **never** be used as the primary key for year-over-year matching.

This is important because:

1. A plan name may change while the CMS code stays the same.
2. A carrier may reuse a similar marketing name while changing the CMS code.
3. A CMS code may terminate and a new CMS code may appear with nearly the same plan name.

Example:

```text
2026:
H5253-184-000
UHC Dual Complete NC-S3

2027:
H5253-216-001
UHC Dual Complete NC-S3
```

These should be treated as different plan records because the CMS code changed.

By contrast:

```text
2026:
H5253-117-000
AARP Medicare Advantage from UHC NC-0015

2027:
H5253-117-000
AARP Medicare Advantage from UHC NC-15
```

This should be treated as the same plan lineage because the CMS code stayed the same.

---

# 3. Source-of-Truth Model

The existing CMS import should remain authoritative.

First Look information should be treated as preliminary carrier-provided data.

Recommended statuses:

```text
first_look
carrier_verified
cms_verified
superseded
needs_review
rejected
```

Definitions:

### `first_look`
Preliminary carrier-released data that has been entered or imported but has not yet been reconciled with CMS.

### `carrier_verified`
First Look data reviewed against an official carrier source document.

### `cms_verified`
The record has been reconciled with official CMS data.

### `superseded`
A First Look record or value has been replaced by a later authoritative record.

### `needs_review`
Data is incomplete, contradictory, or requires human review.

### `rejected`
A submitted value or change was determined to be incorrect.

---

# 4. Important Architectural Principle

Do **not** overwrite official CMS data with First Look data.

First Look data should exist alongside CMS data.

A useful conceptual model is:

```text
plan identity
    ↓
plan version / source
    ↓
plan benefits
    ↓
service area
    ↓
source evidence
```

The application should be capable of showing both:

```text
2027 First Look
2027 CMS Official
```

for the same CMS code.

Later, the system should be able to report discrepancies between the preliminary First Look and final CMS/carrier-confirmed data.

---

# 5. Recommended Database Architecture

Adapt this to the existing schema rather than replacing working tables unnecessarily.

## 5.1 `plans`

Represents the stable plan identity within a contract year.

Suggested fields:

```sql
id
contract_year
cms_code
contract_id
plan_id
segment_id
carrier_id
plan_name
product_type
snp_type
network_type
rx_coverage
created_at
updated_at
```

Suggested constraints:

```text
UNIQUE(contract_year, cms_code)
```

Possible parsed components:

```text
cms_code     = H5253-117-000
contract_id  = H5253
plan_id      = 117
segment_id   = 000
```

---

## 5.2 `plan_versions`

Stores source-specific versions of a plan.

Suggested fields:

```sql
id
plan_id
source_type
data_status
source_document_id
source_effective_date
version_label
submitted_by
verified_by
verified_at
created_at
updated_at
```

Possible `source_type` values:

```text
cms
carrier_first_look
carrier_sob
carrier_summary
manual
community_submission
```

Example:

```text
Plan: H5253-117-000 / 2027

Version 1:
source_type = carrier_first_look
data_status = carrier_verified

Version 2:
source_type = cms
data_status = cms_verified
```

---

# 6. Product Classification

Avoid forcing every plan into one mutually exclusive category when multiple attributes can coexist.

Use separate fields.

## 6.1 Product type

```text
MAPD
MA_ONLY
PDP
```

## 6.2 SNP type

```text
NONE
C_SNP
D_SNP
I_SNP
```

## 6.3 Network type

Examples:

```text
HMO
HMO_POS
PPO
PFFS
```

## 6.4 Independent boolean or numeric attributes

Examples:

```text
has_part_b_giveback
part_b_giveback_monthly

rx_coverage

has_dental
has_vision
has_hearing
has_otc
has_food
has_utilities
has_transportation
has_fitness
has_post_discharge_meals
```

This allows filters such as:

```text
MAPD
AND giveback >= $50
AND dental allowance >= $1,500
AND available in Union County
```

without inventing an artificial plan category called "Giveback."

---

# 7. Canonical Benefit Schema

This is the most important design step.

Carrier terminology varies. The portal should map carrier-specific language into a shared internal schema.

The schema should store both:

1. **structured numeric/boolean values for filtering**
2. **display text for exact benefit wording when needed**

Do not rely only on prose strings if the value may need to be filtered, sorted, compared, or graphed.

---

# 8. Core Financial Fields

Suggested structured fields:

```text
monthly_premium

part_b_giveback_monthly
part_b_giveback_annual

medical_deductible_in_network
medical_deductible_out_of_network

moop_in_network
moop_combined
```

If a value is not applicable, store `NULL`, not `0`, unless the benefit is actually zero.

---

# 9. Medical Benefit Fields

Recommended fields include:

## PCP and specialist

```text
pcp_copay
specialist_copay
referral_required
```

Optional display strings:

```text
pcp_display
specialist_display
```

---

## Inpatient hospital

Avoid storing only:

```text
"$550 per day days 1-5, $0 thereafter"
```

Prefer structured fields:

```text
inpatient_copay_per_day
inpatient_copay_days
inpatient_copay_per_stay
inpatient_after_initial_days_copay
inpatient_display
```

Not every carrier uses the same format, so all structured fields can be nullable.

---

## ASC and outpatient hospital

```text
asc_copay
outpatient_hospital_copay
colonoscopy_copay
```

---

## Emergency and urgent care

```text
er_copay
urgent_care_copay
```

---

## Ambulance

```text
ambulance_ground_copay
ambulance_air_copay
ambulance_coinsurance_percent
ambulance_display
```

---

## Diagnostic services

```text
diagnostic_radiology_copay
xray_copay
advanced_imaging_copay
lab_copay
```

---

# 10. Prescription Drug Fields

For MAPD and PDP products.

## Deductible

Store both structured tier applicability and display wording.

Possible fields:

```text
rx_deductible_amount
rx_deductible_tier_1
rx_deductible_tier_2
rx_deductible_tier_3
rx_deductible_tier_4
rx_deductible_tier_5
rx_deductible_display
```

For LIS-sensitive plans:

```text
rx_deductible_with_lis
```

---

## Retail tiers

Suggested fields:

```text
retail_tier_1
retail_tier_2
retail_tier_3
retail_tier_4
retail_tier_5

retail_tier_1_type
retail_tier_2_type
...
```

Where type may be:

```text
copay
coinsurance
varies_by_lis
not_applicable
```

---

## Mail order

```text
mail_tier_1
mail_tier_2
mail_tier_3
mail_days_supply
```

---

## Insulin

```text
insulin_retail_copay
insulin_mail_copay
```

---

# 11. Supplemental Benefit Fields

## Dental

```text
has_dental
dental_allowance
dental_allowance_period
dental_preventive_copay
dental_comprehensive_coinsurance
dental_rider_available
dental_display
```

---

## Vision

```text
has_vision
routine_eye_exam_copay
vision_allowance
vision_allowance_period_months
vision_display
```

---

## Hearing

```text
has_hearing
hearing_allowance
hearing_allowance_period_months
hearing_device_limit
hearing_display
```

---

## OTC / Food / Utilities

These should be separated even if a carrier combines them in one flex card.

```text
has_otc
otc_amount
otc_frequency

has_food
food_amount
food_frequency

has_utilities
utilities_amount
utilities_frequency

shared_flex_allowance
shared_flex_frequency
```

Also calculate annualized values where useful:

```text
otc_annual_value
food_annual_value
utilities_annual_value
shared_flex_annual_value
```

Example:

```text
$70/month OTC
```

becomes:

```text
otc_amount = 70
otc_frequency = monthly
otc_annual_value = 840
```

This makes filtering and ranking possible.

---

## Transportation

```text
has_transportation
transportation_one_way_trips
transportation_radius_miles
transportation_display
```

---

## Fitness

```text
has_fitness
fitness_display
```

---

## Meals

```text
has_post_discharge_meals
meals_total
meals_period_days
meals_display
```

---

# 12. Service Area Design

Do not store counties as one large comma-separated field.

Use a relational table.

## `plan_service_areas`

Suggested fields:

```sql
id
plan_version_id
state_fips
state_name
county_fips
county_name
created_at
```

Example:

| CMS Code | Year | County |
|---|---:|---|
| H5253-117-000 | 2027 | Mecklenburg |
| H5253-117-000 | 2027 | Union |
| H5253-117-000 | 2027 | Cabarrus |

This should support queries such as:

```text
Show all D-SNPs available in Union County.
```

```text
Show plans available in Mecklenburg but not Union.
```

```text
Show plans available in all of Mecklenburg, Union, Cabarrus, and Iredell.
```

When official CMS service-area data becomes available, the app should be able to compare First Look service areas against CMS service areas.

---

# 13. Source Documents and Evidence

Every First Look value should be traceable to a source.

Recommended table:

## `plan_source_documents`

```sql
id
carrier_id
contract_year
document_type
document_name
file_url
storage_provider
uploaded_by
uploaded_at
notes
```

Possible `document_type` values:

```text
first_look
plan_comparison
summary_of_benefits
evidence_of_coverage
cms_dataset
carrier_broker_guide
other
```

Dropbox may be used as the source-document archive if desired.

Possible folder structure:

```text
Medicare Plan Data/
├── 2026/
│   ├── Aetna/
│   ├── BCBSNC/
│   ├── Devoted/
│   ├── HealthSpring/
│   ├── Humana/
│   └── UHC/
└── 2027/
    ├── Aetna/
    ├── BCBSNC/
    ├── Devoted/
    ├── HealthSpring/
    ├── Humana/
    └── UHC/
```

The database should store the Dropbox URL or file identifier rather than treating Dropbox as the database.

---

# 14. Field-Level Evidence

Ideally, important fields should support evidence metadata.

Possible table:

## `plan_field_evidence`

```sql
id
plan_version_id
field_name
source_document_id
source_page
source_excerpt
submitted_by
verified_by
verification_status
created_at
updated_at
```

Example:

```text
Field:
dental_allowance

Value:
2500

Source:
Humana 2027 First Look

Page:
7

Submitted by:
Michael

Verified by:
Tim
```

This makes the system auditable.

---

# 15. Community / Group-Sourced Workflow

Users should not directly edit production CMS data.

Use a submission/review workflow.

## Roles

### Viewer
Can search, filter, compare, print, and export.

### Contributor
Can submit First Look data and proposed corrections.

### Reviewer
Can approve or reject submitted changes.

### Admin
Can manage users, carriers, years, imports, schemas, and data.

Google Workspace accounts can be used for authentication if that matches the portal's current auth model.

---

# 16. Submission Workflow

Recommended flow:

```text
Contributor submits data
        ↓
Needs Review
        ↓
Reviewer examines source
        ↓
Approved / Rejected
        ↓
Published First Look record
```

A correction should preserve:

```text
old value
proposed value
source
submitter
reviewer
timestamp
reason
```

Do not silently replace data.

---

# 17. Suggested Tables for Community Submissions

## `plan_change_submissions`

```sql
id
plan_version_id
field_name
current_value
proposed_value
source_document_id
source_page
notes
submitted_by
status
reviewed_by
reviewed_at
created_at
```

Possible status values:

```text
pending
approved
rejected
needs_more_info
```

---

# 18. First Look Import Workflow

The system should support structured imports rather than requiring manual entry for every plan.

Potential admin page:

```text
/admin/first-look/import
```

Input:

```text
CSV
JSON
possibly XLSX later
```

Recommended import preview:

```text
Carrier: UnitedHealthcare
Contract Year: 2027

13 plans detected
11 existing CMS-code lineages
2 new CMS codes
3 2026 CMS codes not present in 2027
0 invalid CMS codes
2 warnings
```

Then:

```text
[Review Records]
[Import First Look]
```

The import should never automatically mark records as `cms_verified`.

---

# 19. Example Import JSON

```json
{
  "contract_year": 2027,
  "cms_code": "H5253-117-000",
  "carrier": "UnitedHealthcare",
  "plan_name": "AARP Medicare Advantage from UHC NC-15",
  "product_type": "MAPD",
  "snp_type": "NONE",
  "network_type": "HMO_POS",
  "rx_coverage": true,
  "monthly_premium": 0,
  "part_b_giveback_monthly": 0,
  "moop_in_network": 4450,
  "pcp_copay": 0,
  "specialist_copay": 35,
  "rx_deductible_amount": 685,
  "dental_allowance": 1500,
  "vision_allowance": 150,
  "otc_amount": 25,
  "otc_frequency": "quarterly",
  "data_status": "first_look",
  "source_type": "carrier_first_look"
}
```

---

# 20. CMS Reconciliation Workflow

Once official CMS 2027 data becomes available:

```text
CMS import
    ↓
match on contract_year + cms_code
    ↓
compare First Look vs CMS
    ↓
generate discrepancy report
    ↓
review differences
    ↓
mark verified/superseded
```

Example result:

```text
H5253-117-000

Premium
First Look: $0
CMS: $0
MATCH

MOOP
First Look: $4,450
CMS: $4,450
MATCH

Dental
First Look: $1,500
Final carrier data: $1,250
CHANGED

Service Area
First Look: Mecklenburg, Union
CMS: Mecklenburg, Union, Cabarrus
CHANGED
```

The First Look record should remain historically available rather than being deleted.

---

# 21. Year-over-Year Comparison Engine

Users should be able to compare the same CMS code across contract years.

Example:

```text
H5253-117-000
2026 vs 2027
```

Display:

| Benefit | 2026 | 2027 | Change |
|---|---:|---:|---|
| Premium | $0 | $0 | — |
| MOOP | $4,200 | $4,450 | +$250 |
| Specialist | $35 | $35 | — |
| Rx Deductible | $440 | $685 | +$245 |
| Dental | $2,000 | $1,500 | -$500 |

Changes should be visually classified:

```text
improved
worsened
unchanged
changed_structure
needs_review
```

Do not automatically assume that every numerically higher value is worse. Examples:

- higher giveback = generally better
- higher dental allowance = generally better
- higher MOOP = generally worse
- higher copay = generally worse
- changed hearing-benefit structure may require review

A field-level comparison rule table may be useful.

---

# 22. Comparison Rule Metadata

Possible table:

## `benefit_definitions`

```sql
field_name
display_name
category
data_type
comparison_direction
annualize
filterable
sortable
reportable
```

Example:

| Field | Direction |
|---|---|
| monthly_premium | lower_is_better |
| part_b_giveback_monthly | higher_is_better |
| moop_in_network | lower_is_better |
| specialist_copay | lower_is_better |
| dental_allowance | higher_is_better |
| otc_annual_value | higher_is_better |
| network_type | neutral |
| hearing_display | manual_review |

This prevents hard-coded logic scattered across the application.

---

# 23. New / Continuing / Terminated Logic

For each carrier and contract year, automatically classify CMS codes.

Example:

```text
2026 codes
A B C D

2027 codes
A B D E
```

Results:

```text
A continuing
B continuing
C terminated
D continuing
E new
```

Marketing-name similarity should not override CMS-code matching.

Optionally support a separate manually assigned relationship:

```text
replacement_plan_id
predecessor_plan_id
```

This would allow notation such as:

```text
H5253-184-000 terminated
possible successor: H5253-216-001
```

without falsely treating them as the same CMS plan.

---

# 24. Main Portal UI

Add a plan intelligence area to the existing portal.

Possible navigation:

```text
Plans
├── Search Plans
├── Compare Plans
├── Year-over-Year Changes
├── First Look
├── PDPs
├── Service Areas
└── Data Review
```

---

# 25. Search and Filter UI

Recommended filters:

## Contract Year

```text
2026
2027
```

## Carrier

```text
UnitedHealthcare
HealthSpring
Devoted
Humana
Aetna
BCBS NC
```

## Product Type

```text
MAPD
MA Only
PDP
```

## SNP Type

```text
Standard
C-SNP
D-SNP
```

## Network

```text
HMO
HMO-POS
PPO
```

## County

```text
Mecklenburg
Union
Cabarrus
Iredell
etc.
```

## Drug coverage

```text
With Rx
Without Rx
```

## Giveback

Examples:

```text
Has giveback
>= $25
>= $50
>= $100
>= $150
```

## Premium

Examples:

```text
$0
<= $25
<= $50
custom range
```

## MOOP

Range filter.

## Dental

Examples:

```text
Has dental
>= $1,000
>= $1,500
>= $2,000
>= $3,000
```

## OTC

Examples:

```text
Has OTC
>= $25/month equivalent
>= $50/month equivalent
```

## Other benefits

```text
Food
Utilities
Transportation
Fitness
Post-discharge meals
```

---

# 26. Plan Compare UI

Allow users to select several plans and compare them side-by-side.

Example:

```text
[✓] UHC H5253-117-000
[✓] Humana Hxxxx-xxx-xxx
[✓] Devoted Hxxxx-xxx-xxx

[Compare Selected]
```

Comparison table:

| Benefit | UHC | Humana | Devoted |
|---|---:|---:|---:|
| Premium | $0 | $0 | $0 |
| Giveback | — | $75 | $100 |
| MOOP | $4,450 | $5,900 | $4,900 |
| PCP | $0 | $0 | $0 |
| Specialist | $35 | $40 | $30 |
| Dental | $1,500 | $2,000 | $1,500 |
| OTC | $25/qtr | $50/mo | $40/mo |

Allow:

```text
Print
Export PDF
Export CSV
```

---

# 27. Year-over-Year Reporting

Filters:

```text
Carrier
County
Product Type
SNP Type
Benefit
```

Example report:

```text
UnitedHealthcare
2026 → 2027
Mecklenburg County
MAPD
```

Possible outputs:

### Largest MOOP increases

### Largest premium increases

### Largest giveback increases

### Largest dental reductions

### Largest OTC changes

### New plans

### Terminated plans

### Plans with changed network type

### Plans with new referral requirements

---

# 28. First Look Banner / UI Safety

Any preliminary record should visibly state:

```text
2027 FIRST LOOK
Preliminary carrier-provided plan information.
Not yet verified against official CMS data.
```

Possible badge colors/statuses:

```text
FIRST LOOK
CARRIER VERIFIED
CMS VERIFIED
NEEDS REVIEW
```

This distinction should appear on:

- plan detail pages
- printed reports
- PDF exports
- comparison charts
- search results where practical

---

# 29. PDP Support

PDPs should live in the same general data system but use PDP-specific fields.

## PDP fields

```text
cms_code
carrier
contract_year
monthly_premium
rx_deductible
tier_1_preferred
tier_2_preferred
tier_3_preferred
tier_4_preferred
tier_5_preferred
tier_1_standard
tier_2_standard
tier_3_standard
tier_4_standard
tier_5_standard
mail_tier_1
mail_tier_2
mail_tier_3
insulin_copay
service_area
star_rating
commissionable
data_status
```

The UI should detect `product_type = PDP` and show a PDP-specific comparison layout rather than medical-service fields.

---

# 30. Carrier Scope

Initial carrier support:

```text
UnitedHealthcare
HealthSpring
Devoted
Humana
Aetna
Blue Cross Blue Shield of North Carolina
```

The schema should remain carrier-neutral.

Do not create fields named after a carrier unless the benefit truly cannot be normalized.

Carrier-specific wording should usually go into:

```text
*_display
notes
source_excerpt
```

rather than becoming a new database column.

---

# 31. Data Import Strategy

Initial First Look data will likely come from:

```text
carrier comparison PDFs
carrier broker guides
carrier spreadsheets
manual entry
structured JSON/CSV generated from reviewed source documents
```

Recommended workflow:

```text
PDF
↓
extract
↓
normalize
↓
human review
↓
JSON/CSV
↓
portal import preview
↓
database
```

Do not directly trust automated extraction without a review step.

---

# 32. Validation Rules

At minimum validate:

### CMS code format

Pattern example:

```regex
^[HRS]\d{4}-\d{3}-\d{3}$
```

The exact accepted contract prefixes should be checked against actual CMS data and the application's current rules.

### Contract year

Must be a valid supported year.

### Duplicate

Prevent duplicate:

```text
contract_year + cms_code + source/version
```

### Numeric fields

Examples:

```text
premium >= 0
giveback >= 0
MOOP >= 0
dental allowance >= 0
OTC >= 0
```

### Service area

Use normalized county/FIPS data where possible.

### Plan type consistency

Examples:

```text
PDP should have rx coverage
MA Only may not include Part D
D-SNP must have SNP type D_SNP
```

Warnings may be better than hard errors for some cases.

---

# 33. Data Audit Trail

Every change should be attributable.

Track:

```text
created_by
created_at
updated_by
updated_at
verified_by
verified_at
source_document
source_page
change_reason
```

For important plan data, consider a full append-only change log.

Possible table:

```text
plan_change_history
```

---

# 34. Recommended Development Phases

## Phase 1 — Schema Review

Before coding major UI:

1. Inspect the current PostgreSQL schema.
2. Identify existing CMS plan tables.
3. Determine which current fields already overlap this design.
4. Avoid duplicating fields unnecessarily.
5. Design migrations for First Look/versioning support.
6. Confirm how county/service-area data is currently stored.
7. Confirm existing authentication and user roles.

Deliverable:

```text
schema proposal + migration plan
```

Do not migrate yet until reviewed.

---

## Phase 2 — First Look Data Model

Add:

```text
plan versions
source documents
verification status
community submissions
field-level evidence if practical
```

Deliverable:

```text
database migrations
models
queries
tests
```

---

## Phase 3 — UHC Prototype

Use UnitedHealthcare 2026/2027 as the first implementation test.

Test:

```text
continuing plan
renamed plan with same CMS code
terminated CMS code
new CMS code
MAPD
MA Only
C-SNP
D-SNP
Giveback
```

The UHC dataset provides examples of every important matching scenario.

---

## Phase 4 — First Look Importer

Build:

```text
/admin/first-look/import
```

Support JSON/CSV first.

Features:

```text
upload
validate
preview
duplicate detection
new/continuing/terminated analysis
warnings
import
rollback if practical
```

---

## Phase 5 — Search and Filtering

Implement:

```text
carrier
year
product type
SNP type
county
Rx
giveback
premium
MOOP
dental
OTC
other benefits
```

---

## Phase 6 — Plan Compare

Add multi-select side-by-side plan comparison.

Then add:

```text
print
PDF
CSV
```

---

## Phase 7 — Year-over-Year Engine

Add:

```text
2026 → 2027 comparison
field-level deltas
new plans
terminated plans
largest changes
```

---

## Phase 8 — Community Data Review

Add:

```text
submission workflow
review queue
approval/rejection
change history
source evidence
```

---

## Phase 9 — CMS Reconciliation

Once CMS publishes official contract-year data:

```text
match official CMS records
compare to First Look
generate discrepancies
mark CMS verified
retain historical First Look version
```

---

# 35. Initial Acceptance Criteria

The first usable version should allow an authorized agent to:

1. Open the portal.
2. Select contract year 2027.
3. See First Look plans clearly marked as preliminary.
4. Filter by carrier.
5. Filter by county.
6. Filter by MAPD / MA Only / C-SNP / D-SNP / PDP.
7. Filter by Rx coverage.
8. Filter by minimum Part B giveback.
9. Filter by dental allowance.
10. Filter by OTC allowance.
11. Search by CMS code.
12. Compare multiple plans side by side.
13. Compare a CMS code from 2026 to 2027.
14. Identify new and terminated CMS codes.
15. Print or export a useful plan comparison.
16. View the source document behind a First Look value.
17. Submit a correction.
18. Review and approve/reject corrections.
19. Later reconcile First Look data against official CMS data.

---

# 36. Non-Goals for Initial Release

Do not initially build:

- a public consumer-facing Medicare shopping site
- enrollment functionality
- automated plan recommendation logic
- AI-generated "best plan" recommendations
- a separate application if the existing portal can support this
- uncontrolled direct editing of production CMS data

The first version is an **internal plan intelligence and research tool**.

---

# 37. Security and Compliance Considerations

The system will initially be used internally by agents.

Carrier First Look documents may contain language such as:

```text
For agent use only.
Not intended for use as marketing material for the general public.
```

Therefore:

- First Look data should be treated as internal unless the source permits public use.
- Printed/exported First Look reports should include an appropriate preliminary/internal-use notice.
- User permissions should prevent unauthorized editing.
- CMS-verified and First Look data should never be visually indistinguishable.

---

# 38. Suggested Developer Task for Claude Code

Start by inspecting the existing application rather than immediately generating migrations.

## Task

```text
Review the existing portal.foundersinsuranceagency.com codebase and PostgreSQL schema.

The application already imports and stores CMS Medicare plan data.

Using this specification, determine the smallest clean set of changes required to support:
1. preliminary carrier First Look plan data,
2. source/version tracking,
3. contract-year comparison by CMS code,
4. new/continuing/terminated plan detection,
5. later reconciliation against official CMS data,
6. service-area filtering,
7. community submission/review,
8. plan comparison and reporting.

Do not replace working CMS import logic.

First:
- identify relevant existing tables/models/routes/components,
- explain how current plan data is structured,
- identify what can be reused,
- identify schema gaps,
- propose migrations,
- propose API/backend changes,
- propose UI changes,
- identify risks.

Do not make destructive schema changes without explicit approval.

Use contract_year + full CMS Contract-Plan-Segment code as the canonical comparison key.

Plan marketing names must not be used as the year-over-year matching key.

Design the system so First Look values never silently overwrite CMS-verified values.

After the architecture review, produce an implementation plan broken into small testable phases.
```

---

# 39. Preferred Engineering Approach

Favor:

```text
small migrations
reusable existing models
normalized relational data
strong validation
explicit source status
auditable changes
incremental UI additions
tests for CMS-code matching
```

Avoid:

```text
giant JSON blobs for all benefits unless needed as supplemental raw data
matching by plan name
comma-separated county storage
overwriting CMS records
carrier-specific schema duplication
unreviewed automated imports
hard-coded comparison rules spread throughout frontend code
```

---

# 40. Long-Term Vision

The final portal should become an internal Medicare plan intelligence system.

An agent should be able to ask the system:

```text
Show all 2027 MAPDs in Union County with:
- $0 premium
- at least $50 Part B giveback
- dental allowance >= $1,500
- OTC benefit
```

or:

```text
Show me every 2027 plan in Mecklenburg County that became materially worse from 2026.
```

or:

```text
Compare UHC, Humana, Devoted, Aetna, HealthSpring, and BCBS NC C-SNPs in Cabarrus County.
```

or:

```text
Which 2027 plans are new?
```

or:

```text
Which 2026 CMS codes terminated for 2027?
```

or:

```text
Which First Look values changed when CMS published the final data?
```

The system should answer these from structured, source-traceable plan data rather than requiring agents to manually read dozens of carrier PDFs every year.

---

# 41. Guiding Principle

**CMS data remains authoritative.**

First Look data exists to make the period before official CMS publication useful.

The application should preserve the distinction between:

```text
what the carrier originally announced
what was reviewed internally
what CMS ultimately published
```

while still making all three useful for analysis, reporting, and future contract-year planning.
