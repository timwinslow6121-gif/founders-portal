"""
Sync plan data from CMS Medicare Advantage/PDP Landscape CSV into the plans table.

SOURCE FILE:
  docs/Medicare Landscape Files/CY2026_Landscape_202603/CY2026_Landscape_202603.csv
  (or pass a path as first argument)

WHAT IT UPDATES (fields present in the Landscape file):
  - monthly_premium  (Monthly Consolidated Premium Part C + D)
  - annual_oopm      (In-Network MOOP Amount)
  - star_rating      (Overall Star Rating)
  - service_area     (derived from states the plan appears in)

NOTE: PCP copay, specialist copay, ER copay, and drug tier data are NOT in the
Landscape file — they live in the separate CMS Plan Benefit Package (PBP) files.
This script only syncs what the Landscape file actually contains.

WHAT IT REPORTS (scripts/cms_sync_report.txt):
  - All plans updated with old → new values
  - CMS plans in NC/SC not matched to your DB (flag for manual review)

Run on VPS: ./venv/bin/python3 scripts/sync_cms_plan_data.py [optional/path/to/file.csv]
"""
import sys, os, csv, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

SERVICE_AREA_STATES = {"NC", "SC"}

PLAN_YEAR = 2026

DEFAULT_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "Medicare Landscape Files",
    "CY2026_Landscape_202603", "CY2026_Landscape_202603.csv",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cms_id(contract_id, plan_id):
    """Build H####-### from separate Contract ID and Plan ID columns."""
    cid = str(contract_id).strip()
    # Plan ID is zero-padded to 3 digits (e.g. '117', '034')
    pid = str(plan_id).strip().zfill(3)
    return f"{cid}-{pid}"


def _parse_dollar(val):
    """'$4,200.00 ' → 4200.0, 'Not Applicable' → None."""
    if not val:
        return None
    v = val.strip()
    if v.lower() in ("not applicable", "n/a", ""):
        return None
    # Handle negative values like ($3.90)
    negative = v.startswith("(") and v.endswith(")")
    v = v.strip("()").replace("$", "").replace(",", "").strip()
    try:
        result = float(v)
        return -result if negative else result
    except ValueError:
        return None


def _parse_star(val):
    """'4.0' → 4.0, 'Not Applicable' → None."""
    if not val:
        return None
    v = val.strip()
    if v.lower() in ("not applicable", "n/a", ""):
        return None
    try:
        return float(v)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(csv_path=None):
    csv_path = csv_path or DEFAULT_CSV

    if not os.path.exists(csv_path):
        print(f"❌  File not found: {csv_path}")
        print()
        print("Expected the CMS Landscape CSV at:")
        print(f"  {csv_path}")
        return

    app = create_app()
    with app.app_context():
        agency_id = db.session.execute(
            db.text("SELECT agency_id FROM plans LIMIT 1")
        ).scalar()
        if not agency_id:
            print("No plans in database. Exiting.")
            return

        # Build lookup: "H5253-117" → Plan row
        db_plans = Plan.query.filter_by(agency_id=agency_id, year=PLAN_YEAR).all()
        plan_map = {p.cms_plan_id.strip().upper(): p
                    for p in db_plans if p.cms_plan_id}

        print(f"DB plans with CMS IDs ({PLAN_YEAR}): {len(plan_map)}")
        print(f"Reading: {csv_path}\n")

        # One CMS plan appears once per county — deduplicate, take first NC/SC row
        seen = set()          # cms_ids already processed
        updates = {}          # plan_id → {field: (old, new)} for report
        unmatched = {}        # cms_id → {"name", "org", "states"}

        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for row in reader:
                state = row["State Territory Abbreviation"].strip().upper()
                if state not in SERVICE_AREA_STATES:
                    continue

                cms_id = _cms_id(row["Contract ID"], row["Plan ID"]).upper()

                if cms_id in seen:
                    # Already processed this plan — just track which states it's in
                    if cms_id in unmatched:
                        unmatched[cms_id]["states"].add(state)
                    continue

                seen.add(cms_id)

                db_plan = plan_map.get(cms_id)
                if not db_plan:
                    unmatched[cms_id] = {
                        "name": row.get("Plan Name", "").strip(),
                        "org":  row.get("Organization Marketing Name", "").strip(),
                        "states": {state},
                    }
                    continue

                changes = {}

                # Monthly premium — use consolidated (Part C+D) first, fall back to Part C only
                # (PPO plans without drug coverage have 'Not Applicable' for consolidated)
                premium = (_parse_dollar(row.get("Monthly Consolidated Premium (Part C + D)", ""))
                           or _parse_dollar(row.get("Part C Premium", "")))
                if premium is not None and premium != db_plan.monthly_premium:
                    changes["monthly_premium"] = (db_plan.monthly_premium, premium)
                    db_plan.monthly_premium = premium

                # In-Network MOOP
                moop = _parse_dollar(row.get("In-Network Maximum Out-of-Pocket (MOOP) Amount", ""))
                if moop is not None and moop != db_plan.annual_oopm:
                    changes["annual_oopm"] = (db_plan.annual_oopm, moop)
                    db_plan.annual_oopm = moop

                # Overall Star Rating
                stars = _parse_star(row.get("Overall Star Rating", ""))
                if stars is not None and stars != db_plan.star_rating:
                    changes["star_rating"] = (db_plan.star_rating, stars)
                    db_plan.star_rating = stars

                if changes:
                    updates[db_plan.id] = {"plan": db_plan, "changes": changes}

        db.session.commit()

        # --- Report ---
        lines = [
            f"CMS Landscape Sync Report — {PLAN_YEAR}",
            f"Source: {os.path.basename(csv_path)}",
            "=" * 65, "",
        ]

        lines.append(f"UPDATED ({len(updates)} plans):")
        if updates:
            for entry in sorted(updates.values(), key=lambda e: (e["plan"].carrier, e["plan"].plan_name)):
                p = entry["plan"]
                lines.append(f"\n  {p.carrier} | {p.cms_plan_id} | {p.friendly_name or p.plan_name}")
                for field, (old, new) in entry["changes"].items():
                    lines.append(f"    {field}: {old} → {new}")
        else:
            lines.append("  (no changes — DB already up to date)")

        lines += [
            "",
            "=" * 65,
            f"",
            f"NOT IN YOUR DB ({len(unmatched)} CMS plans in NC/SC not matched):",
            "  Add any you sell via Carriers & Plans → Add Plan.",
            "",
        ]
        for cms_id, info in sorted(unmatched.items()):
            states_str = "/".join(sorted(info["states"]))
            lines.append(f"  {cms_id}  |  {info['org']}  |  {info['name']}  [{states_str}]")

        report_path = os.path.join(os.path.dirname(__file__), "cms_sync_report.txt")
        with open(report_path, "w") as f:
            f.write("\n".join(lines))

        print(f"✅  Updated {len(updates)} plans.")
        print(f"📄  Report: scripts/cms_sync_report.txt")
        print(f"    {len(unmatched)} CMS plans in NC/SC not in your DB")

        # Print the updated plans inline too
        if updates:
            print()
            for entry in sorted(updates.values(), key=lambda e: (e["plan"].carrier, e["plan"].plan_name)):
                p = entry["plan"]
                print(f"  ✓ {p.carrier} {p.cms_plan_id} — {', '.join(entry['changes'].keys())}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
