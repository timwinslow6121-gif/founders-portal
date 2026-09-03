/**
 * Compare Plans dashboard.
 * Builds a tab where you pick plans by CMS code and see their benefits
 * side by side, 2026 vs 2027.
 *
 * Requires a tab named "Master" with these columns:
 *   A CMS Code | B Carrier | C Plan Name | D Year | E Benefit | F Value | G Source
 *
 * Run: buildComparisonDashboard
 */
function buildComparisonDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const master = ss.getSheetByName("Master");
  if (!master) throw new Error('No tab named "Master". Build it first.');

  let dash = ss.getSheetByName("Compare Plans");
  if (!dash) dash = ss.insertSheet("Compare Plans");
  dash.clear();
  dash.getRange(1, 1, dash.getMaxRows(), dash.getMaxColumns()).clearDataValidations();

  // Benefit rows, in the order AJ lays out a chart.
  const benefits = [
    "Premium", "Part B giveback", "Medical deductible", "Max out-of-pocket",
    "PCP", "Specialist", "Referrals", "Inpatient hospital",
    "Outpatient surgery (ASC)", "Emergency room", "Urgent care",
    "Ambulance (ground)", "Rx deductible", "Rx retail (30-day)",
    "Dental - allowance", "Vision - eyeglasses", "Hearing aids",
    "OTC allowance", "Fitness"
  ];

  const NCOL = 6;             // plan/year columns
  const FIRST = 4;            // first benefit row

  dash.getRange("A1").setValue("CMS Code ->");
  dash.getRange("A2").setValue("Plan Name");
  dash.getRange("A3").setValue("Year ->");
  dash.getRange("A1:A3").setFontWeight("bold");
  dash.getRange(FIRST, 1, benefits.length, 1)
      .setValues(benefits.map(function (b) { return [b]; }));

  // Seed: one plan, both years, then blanks.
  dash.getRange(1, 2, 1, NCOL)
      .setValues([["H3146-001", "H3146-001", "", "", "", ""]]);
  dash.getRange(3, 2, 1, NCOL)
      .setValues([["2026", "2027", "", "", "", ""]]);

  // Plan name derived FROM the code, so the two can never disagree.
  dash.getRange(2, 2, 1, NCOL).setFormulaR1C1(
    '=IFERROR(INDEX(FILTER(Master!C3,' +
    ' TRIM(TO_TEXT(Master!C1))=TRIM(TO_TEXT(R1C))), 1), "")'
  );

  // Value lookup: CMS CODE + YEAR + BENEFIT.
  // TO_TEXT/TRIM on both sides: Sheets often turns a pasted "2026" into the
  // NUMBER 2026, and text 2026 never equals number 2026 inside FILTER.
  // Same guard on the code and benefit, for stray spaces from pasting.
  dash.getRange(FIRST, 2, benefits.length, NCOL).setFormulaR1C1(
    '=IFERROR(INDEX(FILTER(Master!C6,' +
    ' TRIM(TO_TEXT(Master!C1))=TRIM(TO_TEXT(R1C)),' +
    ' TRIM(TO_TEXT(Master!C4))=TRIM(TO_TEXT(R3C)),' +
    ' TRIM(TO_TEXT(Master!C5))=TRIM(TO_TEXT(RC1))), 1), "")'
  );

  // Dropdown of every CMS code, so you pick a plan and not a name.
  const codes = master.getRange("A2:A").getValues()
    .map(function (r) { return String(r[0]).trim(); })
    .filter(function (v) { return v && v !== "CMS Code"; });
  const unique = Object.keys(codes.reduce(function (acc, c) {
    acc[c] = 1; return acc;
  }, {})).sort();

  if (unique.length) {
    const rule = SpreadsheetApp.newDataValidation()
      .requireValueInList(unique, true)
      .setAllowInvalid(false)
      .build();
    dash.getRange(1, 2, 1, NCOL).setDataValidation(rule);
  }

  dash.setColumnWidth(1, 190);
  dash.setColumnWidths(2, NCOL, 210);
  dash.getRange(FIRST, 2, benefits.length, NCOL).setWrap(true);
  dash.getRange(1, 1, FIRST + benefits.length, NCOL + 1)
      .setVerticalAlignment("top");
  dash.setFrozenRows(3);
  dash.setFrozenColumns(1);

  SpreadsheetApp.getUi().alert(
    "Compare Plans built.\n\n" +
    unique.length + " plan codes available in the row 1 dropdowns.\n" +
    "Row 3 is the year - type 2026 or 2027."
  );
}
