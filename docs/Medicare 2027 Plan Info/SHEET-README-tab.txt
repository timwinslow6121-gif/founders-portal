Medicare Plan Data 2026-2027 (NC)
Updated 2026-09-03

One tab per carrier. Edit directly - changes are live for everyone.
One row = one plan + one year + one benefit.

SOURCE COLUMN - how much to trust the value
CMS  =  CMS-approved / published. Authoritative.
FL   =  Carrier First Look. PRELIMINARY, benefits can still change.

Put your name + date in 'Verified By' / 'Verified Date' when you check a value.

WHERE THE 2027 DATA STANDS
Aetna         523 rows  CMS-approved (19 plans, from the 2027 Plan Guides)
              13 rows   FL (SilverScript Choice PDP, first look)
BCBS          223 rows  FL (9 plans, First Look 9-3-26, pending CMS approval)
Devoted       567 rows  FL
UHC           316 rows  FL
Humana        113 rows  FL
Healthspring   54 rows  FL
Wellcare        0 rows  - see compliance note below

APPROVED vs FIRST LOOK - these are NOT the same thing
"Pending CMS Approval" = the benefits themselves may still change. First look.
"Not for distribution prior to 10/01" = benefits are FINAL, but CMS bars
marketing next-year plans before Oct 1. That is a calendar restriction, not a
data warning.
Aetna's Plan Guides carry CMS material ID Y0001_8915303_2027_M (the _M means
File & Use approved) - so they are CMS, not FL. BCBS, Devoted and UHC all say
"pending CMS approval" and are genuinely first look.

WELLCARE - DO NOT ADD THEIR BENEFITS
Founders is NOT contracted with Wellcare. We cannot legally market plans we
are not appointed for, so their benefits must not be shown. The 63 Wellcare
2026 PDP rows come from the public CMS Landscape file, which is a different
matter from redistributing a carrier's broker deck. Wellcare's 2027 deck
covers only MA/D-SNP, no PDPs, and says PDPs stay NON-COMMISSIONABLE for 2027.
Any 2027 Wellcare PDP data will come from the CMS Landscape file (~Oct).

HANDLE WITH CARE: Blue Medicare Freedom+ (H3404-004)
Niche PPO for federal retirees. Do NOT build recommendations from this data.
FEHB coverage interacts with Medicare in complicated ways, we have very few
members on it, and a wrong recommendation can permanently damage someone's
coverage. Refer out or escalate. Its values also encode two columns (with vs
without federal retiree benefits) in one string, so they do not chart cleanly.

WHEN FINAL CMS PBP DATA ARRIVES (~December)
Do NOT delete the First Look rows. Add the CMS row alongside and set
Source = CMS. Where CMS differs from the first look, make a note - that shows
which plans we may have described incorrectly during AEP prep.
Aetna's 523 CMS rows do not need superseding; they are already approved.

IF A CARRIER REISSUES ITS FIRST LOOK
Replace that carrier's FL rows entirely - do not merge old and new. BCBS did
this on 9-3-26 and told us to ignore the previous version.

PASTING NEW ROWS - always check the count
A short paste raises no error and looks identical to a complete one. Note how
many rows you expect BEFORE pasting, then filter the tab and confirm you got
them. Append only; never replace a whole tab (that wipes everyone's edits).

GOTCHAS
- 2026 came from CMS (deep clinical detail). Most 2027 came from carrier first
  look sheets (marketing-shaped). The benefit lists DIFFER between the years.
- A blank value means 'not in that year's source', NOT $0.
- Values are free text ($455 days 1-6). Do not assume they are numbers.

COMPLIANCE
CMS marketing rules apply. Naming dental/vision/hearing/OTC makes a piece
regulated MARKETING once it reaches a beneficiary - needs TPMO disclaimer and
carrier filing. Internal agent use is fine.
Nothing here may be shown to a beneficiary before Oct 1.
Label first-look (FL) values as preliminary on any export.
