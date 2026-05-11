"""
Sync plan benefit data from CMS Medicare Advantage Plan Landscape file.

CMS publishes this file annually before AEP at:
  https://www.cms.gov/data-research/statistics-trends-and-reports/
  medicare-advantagepart-d-contract-and-enrollment-data/benefits-data

USAGE:
  1. Download the 2026 MA/PDP Landscape file from the URL above (CSV or ZIP)
  2. Place the CSV in: docs/cms_landscape_2026.csv
  3. Run: ./venv/bin/python3 scripts/sync_cms_plan_data.py

What it does:
  - Matches CMS rows to existing Plan records by cms_plan_id (H-number)
  - Updates: monthly_premium, annual_oopm, pcp_copay, specialist_copay,
             er_copay, drug_tier1, drug_tier2, drug_tier3
  - Filters to your SERVICE_AREA_STATES so you only process relevant plans
  - Writes scripts/cms_sync_unmatched.txt for CMS plans not in your DB
  - Writes scripts/cms_sync_report.txt with a summary of all changes

Run on VPS: ./venv/bin/python3 scripts/sync_cms_plan_data.py [path/to/landscape.csv]
"""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# States you serve — filters the CMS file so you only process relevant plans
SERVICE_AREA_STATES = {"NC", "SC"}

# Default CSV path (relative to project root)
DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "cms_landscape_2026.csv"
)

PLAN_YEAR = 2026

# ---------------------------------------------------------------------------
# CMS Landscape CSV column names (2026 format)
# These may shift slightly year to year — update if CMS changes headers.
# The script will print available columns if it can't find the expected ones.
# ---------------------------------------------------------------------------

# Column name aliases: maps our logical field → list of possible CSV column names
COLUMN_ALIASES = {
    "contract_id":   ["Contract ID", "contract_id", "ContractID"],
    "plan_id":       ["Plan ID", "plan_id", "PlanID", "PBP"],
    "state":         ["State", "state", "State Code"],
    "county":        ["County Name", "county_name", "County"],
    "plan_name":     ["Plan Name", "plan_name", "PlanName"],
    "org_name":      ["Organization Name", "org_name", "Organization"],
    "plan_type":     ["Plan Type", "plan_type", "PlanType"],
    "premium":       ["Monthly Consolidated Premium (incl. Part D)", "Monthly Premium",
                      "Total Monthly Premium", "monthly_premium", "Premium"],
    "oopm":          ["In-Network MOOP", "In Network MOOP", "MOOP Amount",
                      "Maximum Out-of-Pocket Responsibility (In-Network)",
                      "annual_oopm", "MOOP"],
    "pcp_copay":     ["Primary Care Physician Cost-Sharing", "PCP Cost", "PCP Copay",
                      "Primary Care Copay", "In-Network PCP Cost-Sharing"],
    "specialist":    ["Specialist Cost-Sharing", "Specialist Copay",
                      "In-Network Specialist Cost-Sharing"],
    "er_copay":      ["Emergency Room Cost-Sharing", "ER Copay",
                      "In-Network ER Cost-Sharing", "Emergency Cost-Sharing"],
    "tier1":         ["Drug Tier 1 Cost-Sharing", "Tier 1", "Drug Tier 1"],
    "tier2":         ["Drug Tier 2 Cost-Sharing", "Tier 2", "Drug Tier 2"],
    "tier3":         ["Drug Tier 3 Cost-Sharing", "Tier 3", "Drug Tier 3"],
}


def _find_col(headers, aliases):
    """Find the first matching column name from a list of aliases (case-insensitive)."""
    h_lower = {h.lower(): h for h in headers}
    for alias in aliases:
        found = h_lower.get(alias.lower())
        if found:
            return found
    return None


def _build_col_map(headers):
    """Build a dict: logical_name → actual_csv_column (or None if not found)."""
    return {
        field: _find_col(headers, aliases)
        for field, aliases in COLUMN_ALIASES.items()
    }


def _normalize_cms_id(contract_id, plan_id):
    """
    Build the H-number we store in plans.cms_plan_id.
    CMS landscape uses separate Contract ID (H####) and Plan ID (###) columns.
    We store them combined as H####-### (matching the format already in the DB).
    """
    if not contract_id:
        return None
    cid = str(contract_id).strip()
    pid = str(plan_id).strip().lstrip("0") if plan_id else ""
    if pid:
        return f"{cid}-{pid.zfill(3)}"
    return cid


def _clean_value(val):
    """Strip whitespace, return None for empty/N/A values."""
    if val is None:
        return None
    v = str(val).strip()
    if v.lower() in ("", "n/a", "na", "not applicable", "none", "$0.00 copay",):
        return v if "$0" in v else None
    return v


def _format_currency(val):
    """Normalize a currency value like '$1,500' or '1500' → '$1,500'."""
    if val is None:
        return None
    v = str(val).replace(",", "").replace("$", "").strip()
    try:
        f = float(v)
        if f == 0:
            return "$0"
        return f"${f:,.0f}" if f == int(f) else f"${f:,.2f}"
    except ValueError:
        return val  # return as-is if not parseable


def _parse_premium(val):
    """Parse premium to float for DB storage."""
    if val is None:
        return None
    v = str(val).replace(",", "").replace("$", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def _parse_oopm(val):
    """Parse OOPM to float."""
    if val is None:
        return None
    v = str(val).replace(",", "").replace("$", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(csv_path=None):
    csv_path = csv_path or DEFAULT_CSV_PATH

    if not os.path.exists(csv_path):
        print(f"❌ CMS landscape file not found: {csv_path}")
        print()
        print("To get this file:")
        print("  1. Go to: https://www.cms.gov/data-research/statistics-trends-and-reports/")
        print("            medicare-advantagepart-d-contract-and-enrollment-data/benefits-data")
        print(f"  2. Download the {PLAN_YEAR} MA/PDP Landscape Source Data file (CSV)")
        print(f"  3. Save it as: docs/cms_landscape_{PLAN_YEAR}.csv")
        print("  4. Re-run this script")
        return

    app = create_app()
    with app.app_context():
        agency_id = db.session.execute(
            db.text("SELECT agency_id FROM plans LIMIT 1")
        ).scalar()
        if not agency_id:
            print("No plans found. Exiting.")
            return

        # Build lookup: normalized cms_plan_id → Plan row
        db_plans = Plan.query.filter_by(agency_id=agency_id, year=PLAN_YEAR).all()
        plan_map = {}
        for p in db_plans:
            if p.cms_plan_id:
                plan_map[p.cms_plan_id.strip().upper()] = p

        print(f"Loaded {len(plan_map)} plans with CMS IDs in DB for year {PLAN_YEAR}")
        print(f"Processing: {csv_path}\n")

        updated = {}      # plan_id → Plan
        unmatched = {}    # cms_id → {"name", "states", "count"}
        skipped_state = 0

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []

            col = _build_col_map(headers)

            # Warn about missing columns
            missing = [k for k, v in col.items() if v is None and k not in ("tier1","tier2","tier3")]
            if missing:
                print(f"⚠️  Columns not found in CSV: {missing}")
                print(f"   Available columns: {headers[:20]}")
                print()

            for row in reader:
                # State filter
                state_col = col.get("state")
                if state_col:
                    state = (row.get(state_col) or "").strip().upper()
                    if state not in SERVICE_AREA_STATES:
                        skipped_state += 1
                        continue

                # Build CMS plan ID
                contract_col = col.get("contract_id")
                plan_col = col.get("plan_id")
                raw_contract = row.get(contract_col, "") if contract_col else ""
                raw_plan = row.get(plan_col, "") if plan_col else ""
                cms_id = _normalize_cms_id(raw_contract, raw_plan)

                if not cms_id:
                    continue

                cms_id_upper = cms_id.upper()
                db_plan = plan_map.get(cms_id_upper)

                if not db_plan:
                    # Also try without leading zeros in plan segment
                    # e.g. H5253-117 might appear as H5253-0117 or vice versa
                    alt = None
                    if "-" in cms_id_upper:
                        contract_part, plan_part = cms_id_upper.rsplit("-", 1)
                        alt = f"{contract_part}-{int(plan_part):03d}"
                        db_plan = plan_map.get(alt)

                if not db_plan:
                    name_col = col.get("plan_name")
                    name = row.get(name_col, "Unknown") if name_col else "Unknown"
                    if cms_id_upper not in unmatched:
                        unmatched[cms_id_upper] = {"name": name, "states": set(), "count": 0}
                    if state_col:
                        unmatched[cms_id_upper]["states"].add(state)
                    unmatched[cms_id_upper]["count"] += 1
                    continue

                # --- Extract and apply fields ---
                def get(field):
                    c = col.get(field)
                    return _clean_value(row.get(c)) if c else None

                # Premium
                prem = _parse_premium(get("premium"))
                if prem is not None:
                    db_plan.monthly_premium = prem

                # OOPM
                oopm = _parse_oopm(get("oopm"))
                if oopm is not None:
                    db_plan.annual_oopm = oopm

                # Copays (stored as display strings)
                pcp = get("pcp_copay")
                if pcp: db_plan.pcp_copay = pcp

                spec = get("specialist")
                if spec: db_plan.specialist_copay = spec

                er = get("er_copay")
                if er: db_plan.er_copay = er

                # Drug tiers
                t1 = get("tier1")
                if t1: db_plan.drug_tier1 = t1

                t2 = get("tier2")
                if t2: db_plan.drug_tier2 = t2

                t3 = get("tier3")
                if t3: db_plan.drug_tier3 = t3

                updated[db_plan.id] = db_plan

        db.session.commit()
        print(f"✅ Updated {len(updated)} plans with CMS benefit data.")
        print(f"   Skipped {skipped_state:,} rows outside {'/'.join(sorted(SERVICE_AREA_STATES))}")

        # Summary of what was updated
        report_lines = [f"CMS Plan Data Sync — {PLAN_YEAR}", "=" * 60, ""]
        report_lines.append("UPDATED PLANS:")
        for plan in sorted(updated.values(), key=lambda p: (p.carrier, p.plan_name)):
            report_lines.append(
                f"  {plan.carrier} | {plan.cms_plan_id} | {plan.friendly_name or plan.plan_name}"
                f" | ${plan.monthly_premium or '?'}/mo | OOPM ${plan.annual_oopm or '?'}"
            )

        # Write unmatched report
        report_lines += ["", "=" * 60, f"UNMATCHED CMS PLANS ({len(unmatched)} — not in your plans table):"]
        report_lines.append("Review and add via Carriers & Plans → Add Plan if you sell any of these.")
        report_lines.append("")
        for cms_id, info in sorted(unmatched.items()):
            states_str = "/".join(sorted(info["states"]))
            report_lines.append(f"  {cms_id}  |  {info['name']}  |  {states_str}  |  {info['count']} county rows")

        scripts_dir = os.path.dirname(__file__)
        report_path = os.path.join(scripts_dir, "cms_sync_report.txt")
        with open(report_path, "w") as f:
            f.write("\n".join(report_lines))

        print(f"📄 Full report: scripts/cms_sync_report.txt")
        print(f"   {len(unmatched)} CMS plan IDs not matched to your plans table")


if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(csv_arg)
