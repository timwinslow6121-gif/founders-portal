*********************************************************
*	To View: Set notepad format to word wrap	*
*********************************************************


Medicare Advantage (Part C) and Prescription Drug Plans (Part D) List

Data Last Updated: 03/02/2026

*******************************************************************
Revision History

09/26/2025: Initial file release
11/19/2025: Added 2026 Part C Summary, Part D Summary, and Overall Star Ratings
03/02/2026: Updated Sanctioned Plans

*******************************************************************

This Landscape file contains a list of all approved contracts and plans for Medicare Advantage (MA) Plans, Cost Plans, Special Needs Plans (SNP), and stand-alone Prescription Drug Plans (PDP). Information on Employer sponsored plans (Plan ID ≥ 800), Part B only plans, and National PACE plans are not included in this Landscape file. The data within are subject to change as contracts are finalized. Plans under sanction are indicated in the file. Beginning with contract year (CY) 2026, Medicare-Medicaid Plans (MMP) will no longer be included in the Landscape file as the model demonstration is scheduled to conclude in 2025.

The zip file consists of the following files:

CY20YY_Landscape_yyyymm.xlsb		(Excel binary file)
CY20YY_Landscape_yyyymm.csv		(comma delimited file)
CY20YY_Landscape_readme.txt		(text file)

*******************************************************************

Each file contains the following data columns:

Contract Year
Contract Category Type
US Territory
State Territory Abbreviation
State Territory Name
County Name
Contract ID
Plan ID
Segment ID
Contract Plan ID
Contract Plan Segment ID
Sanctioned Plan
Parent Organization Name
Contract Name
Organization Marketing Name
Organization Type
Plan Name
Plan Type
Special Needs Plan (SNP) Indicator
SNP Type
SNP Institutional Type
SNP Institutional Category
Dual Eligible SNP (D-SNP) Integration Status
D-SNP Applicable Integrated Plan (AIP) Identifier
Chronic or Disabling Condition SNP (C-SNP) Condition Type
Medicare Zero-Dollar Cost Sharing D-SNP Plan
Part D Coverage Indicator
National PDP
Drug Benefit Category
Drug Benefit Type
Voluntary De Minimis Program Participant
Part D Basic Premium At or Below Regional Benchmark
Low Income Subsidy (LIS) Auto Enrollment
Offers Drug Tier with No Part D Deductible
Annual Part D Deductible Amount
Part D Basic Premium
Part D Supplemental Premium
Part D Total Premium
Low Income Premium Subsidy (LIPS) Amount
Part D LIPS (CMS Pays)
Part D Low Income Beneficiary Premium Amount
Part D Out-of-Pocket (OOP) Threshold
Part C Premium
Monthly Consolidated Premium (Part C + D)
In-Network Maximum Out-of-Pocket (MOOP) Amount
Part C Summary Star Rating
Part D Summary Star Rating
Overall Star Rating
MA Region Code
MA Region
PDP Region Code
PDP Region



*******************************************************************

Important Notes

*******************************************************************


If importing the data into Excel using text import wizard (or legacy text import wizard), certain columns must be defined as text to avoid losing leading zero information (example, a Plan ID of '001' will appear as '1' if defined as "General" or "Numeric"). The variable names for columns that need be declared as "Text" are "Plan ID", "Segment ID", "PDP_Region_Code", "MA_Region_Code". In addition, due to specific default formats that Excel utilizes, negative premium values will appear in red font and parenthesized.

Note 01:
SNP Institutional Type – For CY 2026, the descriptor values changed. Below is the crosswalk of equivalent values:
Institutional Only = Facility-based Institutional (FI-SNP)
Institutional Equivalent = Institutional-equivalent (IE-SNP)
Institutional and Institutional Equivalent = Hybrid Institutional (HI-SNP)

Note 02:
Dual Eligible SNP (D-SNP) Integration Status – Only applicable to the Dual Eligible Special Needs (D-SNP) Plan Type. Coordination Only (CO) D-SNP, Highly Integrated (HIDE) D-SNP; Fully Integrated (FIDE) D-SNP.

Note 03:
D-SNP Applicable Integrated Plan (AIP) Identifier – Applicable Integrated Plan per the definition at 42 CFR §422.561. Only applicable to the Dual-Eligible Special Needs Plan (D-SNP) Type.

Note 04:
Chronic or Disabling Condition SNP (C-SNP) Condition Type – For CY 2026, several chronic conditions were renamed.
ChronicAlcohol,DrugDependence is now listed as ChronicAlcohol,SubstanceUseDisorders
EndStageLiver is now listed as ChronicGastrointestinalDisease
EndStageRenal is now listed as ChronicKidneyDisease
Chronic conditions that impair vision, hearing (deafness), taste, touch, and smell is listed as ImpairedSenses

Note 05:
Voluntary De Minimis Program Participant – Part D plans that voluntarily participated in the de minimis program. Under the Affordable Care Act (ACA) §3303(a), a Prescription Drug Plan (PDP) or Medicare Advantage (MA) plan with prescription drug coverage (MA-PD) may volunteer to waive the portion of the monthly adjusted basic beneficiary premium that is a de minimis amount above the low-income subsidy (LIS) benchmark for a subsidy eligible individual. The law prohibits CMS from reassigning LIS members from plans who volunteered to waive the de minimis amount. The de minimis annual amount can be found in the annual HPMS memorandum titled, “Annual Release of Part D National Average Bid Amount and Other Part C & D Bid Information.”

Note 06:
Part D Basic Premium At or Below Regional Benchmark – Identifies which Basic Prescription Drug Plans (PDPs) in each region have a premium at or below the LIS benchmark for that region. If this value is either “Yes” or “No” and the Voluntary De Minimis Program Participant is “Yes,” then the plan will be treated as a plan with a basic Part D premium under the LIS benchmark.
 
Note 07:
Low Income Subsidy (LIS) Auto Enrollment – In accordance with 42 CFR §423.780, full LIS individuals are entitled to a premium subsidy equal to 100 percent of the premium subsidy amount. Basic stand-alone Prescription Drug Plans (PDPs) with monthly premiums at or below the regional LIS premium amount qualify for automatic enrollment of LIS beneficiaries with the full premium subsidy. CMS will identify and assign full-benefit dual-eligible LIS beneficiaries to Basic PDPs with premiums at or below the regional LIS Premium amount when the beneficiary first qualifies. For more information on LIS Auto Enrollment refer to: https://www.cms.gov/medicare/enrollment-renewal/part-d-plans/low-income-subsidy/auto-and-facilitated-enrollment-low-income-beneficiaries

Note 08:
Offers Drug Tier with No Part D Deductible – Indicates whether a plan offers drug tier(s) in which the deductible will NOT apply, meaning drugs on some tiers are covered before satisfying the deductible. For additional information, the “Monthly and Quarterly Prescription Drug Plan Formulary and Pharmacy Network Information” is available on data.cms.gov, which includes specific information on whether a deductible applies to a tier. Defined standard plans do not offer tiers; actuarial equivalent plans are not permitted to modify the Part D deductible amount. As such, defined standard and actuarial equivalent plans will reflect “Not Applicable.” Plans that have a $0.00 deductible amount will also reflect “Not Applicable.” 

Note 09: 
Part D Basic Premium – The dollar amount of the Part D Basic Premium. The Part D Basic Premium covers the basic prescription benefit only and does not cover enhanced drug benefits, medical benefits, or hospital benefits. The Part D Basic Premium is the net of any Part A/B rebates applied to "buy down" the drug premium for Medicare Advantage plans. Beneficiaries are also responsible for their Part B premium and any premiums for Medigap coverage to meet their individual needs.

Note 10: 
Part D Supplemental Premium – The dollar amount of the Part D Supplemental (Enhanced) Premium. This amount is net of any Part A/B rebates applied to "buy down" the drug premium for Medicare Advantage plans. The Part D Supplemental Premium covers any enhanced benefits that may be offered by a plan above and beyond the basic (standard) Part D benefit. These benefits may include lower copayments than the standard benefit, reduced deductible, or coverage of non-Part D drugs.

Note 11:
Part D Total Premium – The dollar amount of the Part D Total (basic + supplemental) Premium (Net of Rebates). The Part D Total Premium is the sum of the Basic and Supplemental Premiums. This amount is net of any Part A/B rebates applied to "buy down" the drug premium for Medicare Advantage plans.

Note 12:
Low Income Premium Subsidy (LIPS) Amount – This data comes from the Medicare Advantage Rate Book and Prescription Drug rate information. Select the appropriate contract year and search for the “Regional Rates and Benchmarks” for more details located at https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/ratebooks-supporting-data. Actual benefit rates may be rounded subject to Social Security Administration (SSA) calculations.  

Note 13:
Part D LIPS (CMS Pays) – The dollar amount of the monthly Part D low-income premium subsidy (LIPS). This is the amount Medicare Part D Extra Help program contributes to help Medicare beneficiaries with limited income and resources pay for prescription drug coverage premiums.

Note 14:
Part D Low Income Beneficiary Premium Amount – The dollar amount of the monthly Part D premium paid by low-income beneficiaries. This is the premium amount the beneficiary pays after the premium subsidy (from the Medicare Part D Extra Help program) has been applied. For more information, refer to CMS memo titled, “Annual Release of Part D National Average Monthly Bid Amount and Other Part C & D Bid Information.”

Note 15:
Part D Out-of-Pocket (OOP) Threshold – The annual Part D OOP Threshold amount as required under section 1860D-2(b)(4)(B)(i)(VII) of the Social Security Act and amended by section 11201 of the Inflation Reduction Act (IRA). More information and changes regarding the annual OOP Threshold amounts can be found in the annual Announcement of Medicare Advantage (MA) Capitation Rates and Part C and Part D Payment Policies available at https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/announcements-and-documents.

Note 16:
Part C Premium – The dollar amount of the Medicare Advantage (referred to as Medicare Part C) Basic Plus Mandatory Supplemental Premium (Net of Rebates). The Part C premium for Medicare Advantage Plans, Cost Plans, and Demonstrations cover Medicare medical and hospital benefits, and supplemental benefits, when offered.

Note 17:
Monthly Consolidated Premium (Part C + D) – To calculate this value, it is the sum of the Part C Premium and the Part D Total Premium. Both Part C and Part D premium must be available for this consolidated value to be applicable.

Note 18:
In-Network Maximum Out-of-Pocket (MOOP) Amount – The limit on enrollee spending that includes costs for all in-network Part A and Part B Services. “Not Applicable” as indicated. Cost plans and Medicare Medical Savings Account (MSA) plans are not subject to the MOOP requirement. However, Cost plans have the option to set a MOOP amount. The MOOP amounts for PFFS plans include both in and out-of-network benefits, which is referred to as a combined MOOP.