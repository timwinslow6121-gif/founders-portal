"""
Sync CMS PBP extended benefits into Plan.details_json + drug_tier4/5 columns.

Reads 9 CMS PBP flat files from docs/Medicare Landscape Files/pbp-benefits-2026/:
  b1a (inpatient hospital), b2 (SNF), b9 (outpatient surgery), b10 (ambulance),
  b16 (dental), b17 (vision/eyewear), b18 (hearing),
  mrx + mrx_tier (drug deductible + tier 4/5 copays).

Writes benefit values as human-readable strings (e.g., "$455 days 1-6, $0 days 7-90")
to Plan.details_json (merge, not overwrite) and Plan.drug_tier4 / drug_tier5 columns.

OTC, healthy_food_card, transportation, gym are NOT synced — they require manual
admin entry (CMS source files b13/b13i have complex VBID structure not cleanly mappable).

Usage:
  ./venv/bin/python3 scripts/sync_pbp_extended_benefits.py [optional/path/to/pbp-dir]

Default pbp-dir: docs/Medicare Landscape Files/pbp-benefits-2026/

Writes report to: scripts/pbp_extended_sync_report.txt
"""
import sys, os, csv, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan

PLAN_YEAR = 2026

DEFAULT_PBP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "Medicare Landscape Files", "pbp-benefits-2026",
)

REPORT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "pbp_extended_sync_report.txt",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tsv(filepath):
    """Load tab-delimited PBP file. Returns list of dicts."""
    with open(filepath, newline="", encoding="cp1252") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _build_lookup(rows, segment="0"):
    """Build {(hnumber_upper, plan_id_str): row} dict filtered by segment_id."""
    lookup = {}
    for row in rows:
        if row.get("segment_id", "").strip() != segment:
            continue
        key = (
            row.get("pbp_a_hnumber", "").strip().upper(),
            row.get("pbp_a_plan_identifier", "").strip(),
        )
        lookup[key] = row
    return lookup


def _build_tier_lookup(rows, segment="0"):
    """Build {(hnumber, plan_id): {tier_id_str: row}} for mrx_tier (multiple rows per plan)."""
    lookup = {}
    for row in rows:
        if row.get("segment_id", "").strip() != segment:
            continue
        key = (
            row.get("pbp_a_hnumber", "").strip().upper(),
            row.get("pbp_a_plan_identifier", "").strip(),
        )
        tier_id = row.get("mrx_tier_id", "").strip()
        lookup.setdefault(key, {})[tier_id] = row
    return lookup


def _parse_cms_plan_id(cms_plan_id):
    """'H5253-117' -> ('H5253', '117') -- strips leading zeros from plan_id."""
    parts = (cms_plan_id or "").strip().upper().split("-")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return (parts[0], str(int(parts[1])))


def _fmt_money(raw):
    """'455.00' -> '$455'; '0.00' -> '$0'; '' -> None."""
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        val = float(raw)
        if val == int(val):
            return f"${int(val):,}"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Per-file extractor functions
# ---------------------------------------------------------------------------

def _extract_inpatient_hospital(row):
    """Build string like '$455 days 1-6, $0 days 7-90' from b1a tiered intervals."""
    if not row or row.get("pbp_b1a_copay_yn", "").strip() != "1":
        return None
    try:
        num_intervals = int(row.get("pbp_b1a_copay_mcs_int_num_t1", "0").strip() or "0")
    except ValueError:
        num_intervals = 0
    parts = []
    for i in range(1, num_intervals + 1):
        amt = row.get(f"pbp_b1a_copay_mcs_amt_int{i}_t1", "").strip()
        bgn = row.get(f"pbp_b1a_copay_mcs_bgnd_int{i}_t1", "").strip()
        end = row.get(f"pbp_b1a_copay_mcs_endd_int{i}_t1", "").strip()
        money = _fmt_money(amt)
        if money and bgn and end:
            parts.append(f"{money} days {bgn}-{end}")
    return ", ".join(parts) if parts else None


def _extract_snf(row):
    """Build string like '$0 days 1-20, $218 days 21-100' from b2 tiered intervals."""
    if not row or row.get("pbp_b2_copay_yn", "").strip() != "1":
        return None
    try:
        num_intervals = int(row.get("pbp_b2_copay_mcs_int_num_t1", "0").strip() or "0")
    except ValueError:
        num_intervals = 0
    parts = []
    for i in range(1, num_intervals + 1):
        amt = row.get(f"pbp_b2_copay_mcs_amt_int{i}_t1", "").strip()
        bgn = row.get(f"pbp_b2_copay_mcs_bgnd_int{i}_t1", "").strip()
        end = row.get(f"pbp_b2_copay_mcs_endd_int{i}_t1", "").strip()
        money = _fmt_money(amt)
        if money and bgn and end:
            parts.append(f"{money} days {bgn}-{end}")
    return ", ".join(parts) if parts else None


def _extract_outpatient_surgery(row):
    """Outpatient surgery copay from b9."""
    if not row:
        return None
    amt = row.get("pbp_b9a_copay_ohs_amt_min", "").strip() or row.get("pbp_b9a_copay_ohs_amt_max", "").strip()
    return _fmt_money(amt)


def _extract_ambulance(row):
    """Ambulance copay from b10."""
    if not row:
        return None
    amt = row.get("pbp_b10a_copay_gas_amt_min", "").strip() or row.get("pbp_b10a_copay_gas_amt_max", "").strip()
    return _fmt_money(amt)


def _extract_dental(row):
    """Dental annual plan max (comprehensive)."""
    if not row:
        return None
    amt = row.get("pbp_b16b_maxplan_pv_amt", "").strip()
    money = _fmt_money(amt)
    return f"{money}/yr" if money else None


def _extract_vision(row):
    """Vision eyewear allowance."""
    if not row:
        return None
    amt = row.get("pbp_b17b_maxenr_amt", "").strip() or row.get("pbp_b17b_comb_maxplan_amt", "").strip()
    return _fmt_money(amt)


def _extract_hearing(row):
    """Hearing aid allowance."""
    if not row:
        return None
    amt = row.get("pbp_b18b_maxenr_amt", "").strip()
    return _fmt_money(amt)


def _extract_drug_deductible(row):
    """Drug deductible from mrx file."""
    if not row:
        return None
    return _fmt_money(row.get("mrx_alt_ded_amount", "").strip())


def _extract_drug_exempt_tiers(row):
    """Drug deductible exempt tiers (bitmask string like '0110000' -> 'Tiers 2, 3')."""
    if not row:
        return None
    bitmask = row.get("mrx_alt_no_ded_tier", "").strip()
    if not bitmask:
        return None
    tiers = [str(i + 1) for i, ch in enumerate(bitmask) if ch == "1"]
    return f"Tiers {', '.join(tiers)}" if tiers else None


def _extract_tier_copay(tier_row):
    """Extract per-tier 30-day retail standard copay; fallback to coinsurance percent."""
    if not tier_row:
        return None
    copay = tier_row.get("mrx_tier_rstd_copay_1m", "").strip()
    money = _fmt_money(copay)
    if money and money != "$0":
        return money
    coins = tier_row.get("mrx_tier_rstd_coins_1m", "").strip()
    try:
        if coins and float(coins) > 0:
            return f"{coins}% coinsurance"
    except (ValueError, TypeError):
        pass
    return money  # may be "$0" or None


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

def _merge_details(plan, updates):
    """Merge updates dict into plan.details_json preserving existing keys."""
    existing = {}
    if plan.details_json:
        try:
            existing = json.loads(plan.details_json)
        except (json.JSONDecodeError, TypeError):
            existing = {}
    for key, val in updates.items():
        if val is not None:
            existing[key] = val
    plan.details_json = json.dumps(existing)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(pbp_dir=None):
    pbp_dir = pbp_dir or DEFAULT_PBP_DIR

    files = {
        "b1a":      os.path.join(pbp_dir, "pbp_b1a_inpat_hosp.txt"),
        "b2":       os.path.join(pbp_dir, "pbp_b2_snf.txt"),
        "b9":       os.path.join(pbp_dir, "pbp_b9_outpat_hosp.txt"),
        "b10":      os.path.join(pbp_dir, "pbp_b10_amb_trans.txt"),
        "b16":      os.path.join(pbp_dir, "pbp_b16_dental.txt"),
        "b17":      os.path.join(pbp_dir, "pbp_b17_eye_exams_wear.txt"),
        "b18":      os.path.join(pbp_dir, "pbp_b18_hearing_exams_aids.txt"),
        "mrx":      os.path.join(pbp_dir, "pbp_mrx.txt"),
        "mrx_tier": os.path.join(pbp_dir, "pbp_mrx_tier.txt"),
    }

    for name, path in files.items():
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}")
            return

    print(f"Loading PBP flat files from: {pbp_dir}")
    lookups = {}
    for k in ("b1a", "b2", "b9", "b10", "b16", "b17", "b18", "mrx"):
        lookups[k] = _build_lookup(_load_tsv(files[k]))
        print(f"  {k}: {len(lookups[k])} plans loaded")
    tier_lookup = _build_tier_lookup(_load_tsv(files["mrx_tier"]))
    print(f"  mrx_tier: {len(tier_lookup)} plan keys loaded\n")

    app = create_app()
    with app.app_context():
        agency_id = db.session.execute(
            db.text("SELECT agency_id FROM plans LIMIT 1")
        ).scalar()
        if not agency_id:
            print("No plans in database. Exiting.")
            return

        db_plans = Plan.query.filter_by(agency_id=agency_id, year=PLAN_YEAR).all()
        print(f"Plans with year={PLAN_YEAR}: {len(db_plans)}\n")

        updated_count = 0
        not_found_per_file = {k: [] for k in files}
        updated_plans_log = []

        for plan in db_plans:
            if not plan.cms_plan_id:
                continue
            key = _parse_cms_plan_id(plan.cms_plan_id)
            if not key:
                continue

            benefit_updates = {}
            fields_written = []

            # b1a -> inpatient_hospital
            r = lookups["b1a"].get(key)
            if r:
                val = _extract_inpatient_hospital(r)
                if val:
                    benefit_updates["inpatient_hospital"] = val
                    fields_written.append("inpatient_hospital")
            else:
                not_found_per_file["b1a"].append(plan.cms_plan_id)

            # b2 -> snf
            r = lookups["b2"].get(key)
            if r:
                val = _extract_snf(r)
                if val:
                    benefit_updates["snf"] = val
                    fields_written.append("snf")
            else:
                not_found_per_file["b2"].append(plan.cms_plan_id)

            # b9 -> outpatient_surgery
            r = lookups["b9"].get(key)
            if r:
                val = _extract_outpatient_surgery(r)
                if val:
                    benefit_updates["outpatient_surgery"] = val
                    fields_written.append("outpatient_surgery")
            else:
                not_found_per_file["b9"].append(plan.cms_plan_id)

            # b10 -> ambulance
            r = lookups["b10"].get(key)
            if r:
                val = _extract_ambulance(r)
                if val:
                    benefit_updates["ambulance"] = val
                    fields_written.append("ambulance")
            else:
                not_found_per_file["b10"].append(plan.cms_plan_id)

            # b16 -> dental_allowance
            r = lookups["b16"].get(key)
            if r:
                val = _extract_dental(r)
                if val:
                    benefit_updates["dental_allowance"] = val
                    fields_written.append("dental_allowance")
            else:
                not_found_per_file["b16"].append(plan.cms_plan_id)

            # b17 -> vision_allowance
            r = lookups["b17"].get(key)
            if r:
                val = _extract_vision(r)
                if val:
                    benefit_updates["vision_allowance"] = val
                    fields_written.append("vision_allowance")
            else:
                not_found_per_file["b17"].append(plan.cms_plan_id)

            # b18 -> hearing
            r = lookups["b18"].get(key)
            if r:
                val = _extract_hearing(r)
                if val:
                    benefit_updates["hearing"] = val
                    fields_written.append("hearing")
            else:
                not_found_per_file["b18"].append(plan.cms_plan_id)

            # mrx -> drug_deductible + drug_deductible_exempt_tiers
            r = lookups["mrx"].get(key)
            if r:
                ded = _extract_drug_deductible(r)
                if ded:
                    benefit_updates["drug_deductible"] = ded
                    fields_written.append("drug_deductible")
                exempt = _extract_drug_exempt_tiers(r)
                if exempt:
                    benefit_updates["drug_deductible_exempt_tiers"] = exempt
                    fields_written.append("drug_deductible_exempt_tiers")
            else:
                not_found_per_file["mrx"].append(plan.cms_plan_id)

            # mrx_tier -> drug_tier4 / drug_tier5 (DB columns, not details_json)
            tier_rows = tier_lookup.get(key, {})
            if tier_rows:
                if "4" in tier_rows:
                    t4 = _extract_tier_copay(tier_rows["4"])
                    if t4:
                        plan.drug_tier4 = t4
                        fields_written.append("drug_tier4")
                if "5" in tier_rows:
                    t5 = _extract_tier_copay(tier_rows["5"])
                    if t5:
                        plan.drug_tier5 = t5
                        fields_written.append("drug_tier5")
            else:
                not_found_per_file["mrx_tier"].append(plan.cms_plan_id)

            if benefit_updates:
                _merge_details(plan, benefit_updates)
            if fields_written:
                updated_count += 1
                updated_plans_log.append((plan.cms_plan_id, plan.plan_name, fields_written))

        db.session.commit()

        # Write report
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("PBP Extended Benefits Sync Report\n")
            f.write("=================================\n")
            f.write(f"PBP dir: {pbp_dir}\n")
            f.write(f"Plan year: {PLAN_YEAR}\n")
            f.write(f"Agency ID: {agency_id}\n")
            f.write(f"Plans processed: {len(db_plans)}\n")
            f.write(f"Plans updated: {updated_count}\n\n")

            f.write("UPDATED PLANS\n-------------\n")
            for cms_id, name, fields in updated_plans_log:
                f.write(f"  {cms_id}  {name}\n    fields: {', '.join(fields)}\n")

            f.write("\nNOT FOUND PER FILE (PDP plans expected here for b1a/b2/b9/b10/b16/b17/b18)\n")
            f.write("-------------------\n")
            for file_key, missing in not_found_per_file.items():
                if missing:
                    f.write(f"  {file_key}: {len(missing)} plans not found: {', '.join(sorted(set(missing)))}\n")

            f.write("\nMANUAL ENTRY REQUIRED (NO CMS SOURCE)\n")
            f.write("-------------------------------------\n")
            f.write("  otc_allowance, healthy_food_card, transportation, gym\n")
            f.write("  (CMS b13 file has complex VBID structure not cleanly mappable; admin form entry only)\n")

        print(f"Sync complete. {updated_count} plans updated. Report: {REPORT_PATH}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
