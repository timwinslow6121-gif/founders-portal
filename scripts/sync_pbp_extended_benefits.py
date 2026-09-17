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
import sys, os, csv, json, argparse, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan
from app.plan_provenance import set_cms_value, make_value

DEFAULT_PLAN_YEAR = 2026

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_pbp_dir(year):
    """CMS publishes one PBP release per contract year: pbp-benefits-<year>/."""
    return os.path.join(
        _REPO_ROOT, "docs", "Medicare Landscape Files", f"pbp-benefits-{year}",
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


def _build_lookup(rows):
    """Build {(hnumber_upper, plan_id_str): row} using the lowest segment_id per plan."""
    # Collect all rows per key, then pick lowest segment (0 if present, else min available)
    candidates = {}
    for row in rows:
        key = (
            row.get("pbp_a_hnumber", "").strip().upper(),
            row.get("pbp_a_plan_identifier", "").strip(),
        )
        seg = row.get("segment_id", "").strip()
        try:
            seg_int = int(seg)
        except ValueError:
            seg_int = 999
        existing_seg = candidates.get(key, (None, 999))[1]
        if seg_int < existing_seg:
            candidates[key] = (row, seg_int)
    return {key: val[0] for key, val in candidates.items()}


def _build_tier_lookup(rows):
    """Build {(hnumber, plan_id): {tier_id_str: row}} using lowest segment_id per plan."""
    # First pass: find lowest segment per plan key
    best_seg = {}
    for row in rows:
        key = (
            row.get("pbp_a_hnumber", "").strip().upper(),
            row.get("pbp_a_plan_identifier", "").strip(),
        )
        seg = row.get("segment_id", "").strip()
        try:
            seg_int = int(seg)
        except ValueError:
            seg_int = 999
        if seg_int < best_seg.get(key, 999):
            best_seg[key] = seg_int
    # Second pass: collect tier rows for the best segment only
    lookup = {}
    for row in rows:
        key = (
            row.get("pbp_a_hnumber", "").strip().upper(),
            row.get("pbp_a_plan_identifier", "").strip(),
        )
        seg = row.get("segment_id", "").strip()
        try:
            seg_int = int(seg)
        except ValueError:
            seg_int = 999
        if seg_int != best_seg.get(key, 999):
            continue
        tier_id = row.get("mrx_tier_id", "").strip()
        lookup.setdefault(key, {})[tier_id] = row
    return lookup


def _parse_cms_plan_id(cms_plan_id):
    """'H5253-117' -> ('H5253', '117'); 'H3449-023-001' -> ('H3449', '023') (segment suffix dropped)."""
    parts = (cms_plan_id or "").strip().upper().split("-")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    # Preserve leading zeros to match PBP file plan_identifier format (e.g. '004' not '4')
    # Third segment (e.g. '-001' in 'H3449-023-001') is a portal segment suffix, not part of PBP key
    return (parts[0], parts[1])


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
    """Outpatient surgery copay from b9. Uses obs (observation/inpatient) max copay."""
    if not row:
        return None
    # b9a_copay_obs = observation stay copay; use max (min is waived/zero portion for some tiers)
    amt = row.get("pbp_b9a_copay_obs_amt_max", "").strip() or row.get("pbp_b9a_copay_obs_amt_min", "").strip()
    if not amt or amt == "0.00":
        # fallback: outpatient hospital surgery copay max
        amt = row.get("pbp_b9a_copay_ohs_amt_max", "").strip()
    return _fmt_money(amt)


def _extract_ambulance(row):
    """Ambulance copay from b10 — separate ground vs air amounts."""
    if not row:
        return None
    ground = _fmt_money(row.get("pbp_b10a_copay_gas_amt_max", "").strip()
                        or row.get("pbp_b10a_copay_gas_amt_min", "").strip())
    air = _fmt_money(row.get("pbp_b10a_copay_aas_amt_max", "").strip()
                     or row.get("pbp_b10a_copay_aas_amt_min", "").strip())
    # Check for air coinsurance (some plans use % instead of flat copay)
    air_coins = row.get("pbp_b10a_coins_aas_pct", "").strip()
    if not air and air_coins:
        try:
            if float(air_coins) > 0:
                air = f"{int(float(air_coins))}% coinsurance"
        except (ValueError, TypeError):
            pass
    if ground and air and ground != air:
        return f"Ground: {ground} / Air: {air}"
    return ground or air


def _extract_dental(row):
    """Dental allowance: preventive max + comprehensive coinsurance rate."""
    if not row:
        return None
    # b16b = preventive/basic dental allowance
    prev_amt = _fmt_money(row.get("pbp_b16b_maxplan_pv_amt", "").strip())
    # b16c comprehensive coinsurance (50% is typical)
    comp_coins = row.get("pbp_b16c_coins_rs_pct", "").strip()  # restorative is most common
    if not comp_coins:
        # try any comprehensive coinsurance column
        for col in ("pbp_b16c_coins_end_pct", "pbp_b16c_coins_peri_pct", "pbp_b16c_coins_prm_pct"):
            comp_coins = row.get(col, "").strip()
            if comp_coins:
                break
    per_code = row.get("pbp_b16b_maxplan_pv_per", "").strip()
    per_map = {"1": "/mo", "2": "/qtr", "3": "/yr", "6": "/period"}
    period = per_map.get(per_code, "/yr")
    if prev_amt and comp_coins:
        try:
            pct = int(float(comp_coins))
            return f"{prev_amt}{period} preventive; {pct}% coinsurance comprehensive"
        except (ValueError, TypeError):
            pass
    return f"{prev_amt}{period}" if prev_amt else None


def _extract_vision(row):
    """Vision eyewear allowance with frequency."""
    if not row:
        return None
    amt = _fmt_money(row.get("pbp_b17b_comb_maxplan_amt", "").strip()
                     or row.get("pbp_b17b_maxenr_amt", "").strip())
    per_code = row.get("pbp_b17b_comb_maxplan_per", "").strip()
    per_map = {"1": "/yr", "2": "/2yr", "3": "/3yr"}
    period = per_map.get(per_code, "")
    return f"{amt}{period}" if amt else None


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

def _write_benefits(plan, updates, cms_source, actions):
    """Write CMS benefit values through the provenance seam.

    Replaces the previous blind `details_json` merge. CLAUDE.md requires that
    ALL _meta writes go through app/plan_provenance.py: a blind merge silently
    overwrites an agent-entered or human-verified value, which is exactly the
    BCBS first-look-vs-CMS incident that engine exists to prevent.

    PBP benefits are compound strings ("$455 days 1-6, $0 days 7-90") with no
    single numeric amount, so they are stored as unit="text" with the benefit
    carried in `display`. set_cms_value compares text values on `display`.

    Mutates `actions` (a Counter) with the per-field outcome so the caller can
    report how many values were written / refreshed / overwrote a first look /
    flagged a conflict / were skipped because a human had verified them.
    """
    for key, val in updates.items():
        if val is None:
            continue
        action = set_cms_value(
            plan, key, make_value(amount=None, unit="text", display=val), cms_source
        )
        actions[action] += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(pbp_dir=None, plan_year=DEFAULT_PLAN_YEAR):
    pbp_dir = pbp_dir or default_pbp_dir(plan_year)
    cms_source = f"cms_pbp_{plan_year}"

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

        db_plans = Plan.query.filter_by(agency_id=agency_id, year=plan_year).all()
        print(f"Plans with year={plan_year}: {len(db_plans)}\n")

        updated_count = 0
        not_found_per_file = {k: [] for k in files}
        updated_plans_log = []
        actions = collections.Counter()

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

            # mrx_tier -> drug_tier1/2/3 (DB columns) + drug_tier4/5 (DB columns)
            tier_rows = tier_lookup.get(key, {})
            if tier_rows:
                tier_col_map = {
                    "1": ("drug_tier1", None),    # (db_col, details_json_key)
                    "2": ("drug_tier2", None),
                    "3": ("drug_tier3", None),
                    "4": ("drug_tier4", None),
                    "5": ("drug_tier5", None),
                }
                for tier_id, (col, _) in tier_col_map.items():
                    if tier_id in tier_rows:
                        val = _extract_tier_copay(tier_rows[tier_id])
                        if val and hasattr(plan, col):
                            setattr(plan, col, val)
                            fields_written.append(col)
            else:
                not_found_per_file["mrx_tier"].append(plan.cms_plan_id)

            if benefit_updates:
                _write_benefits(plan, benefit_updates, cms_source, actions)
            if fields_written:
                updated_count += 1
                updated_plans_log.append((plan.cms_plan_id, plan.plan_name, fields_written))

        db.session.commit()

        # Write report
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("PBP Extended Benefits Sync Report\n")
            f.write("=================================\n")
            f.write(f"PBP dir: {pbp_dir}\n")
            f.write(f"Plan year: {plan_year}\n")
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

            f.write("\nPROVENANCE OUTCOMES (via set_cms_value)\n")
            f.write("--------------------------------------\n")
            if actions:
                for act, n in sorted(actions.items(), key=lambda kv: -kv[1]):
                    f.write(f"  {act:<22} {n}\n")
                if actions.get("conflict_flagged"):
                    f.write("  ^ conflict_flagged: CMS disagrees with an agent-entered value.\n")
                    f.write("    The agent value was NOT overwritten. Review at the plan's conflict queue.\n")
            else:
                f.write("  (no benefit values written)\n")

            f.write("\nSCALAR COLUMNS WRITTEN DIRECTLY (NOT PROVENANCE-TRACKED)\n")
            f.write("-------------------------------------------------------\n")
            f.write("  drug_tier1..drug_tier5 are real DB columns, not details_json keys,\n")
            f.write("  so set_cms_value() cannot track them - it only writes details_json._meta.\n")
            f.write("  They are overwritten wholesale by each sync. Known gap; see BACKLOG.md.\n")

            f.write("\nMANUAL ENTRY REQUIRED (NO CMS SOURCE)\n")
            f.write("-------------------------------------\n")
            f.write("  otc_allowance, healthy_food_card, transportation, gym\n")
            f.write("  (CMS b13 file has complex VBID structure not cleanly mappable; admin form entry only)\n")

        summary = " \u00b7 ".join(f"{a} {n}" for a, n in sorted(actions.items(), key=lambda kv: -kv[1]))
        print(f"Sync complete. {updated_count} plans updated. Report: {REPORT_PATH}")
        if summary:
            print(f"  provenance: {summary}")
        if actions.get("conflict_flagged"):
            print(f"  \u26a0 {actions['conflict_flagged']} conflict(s) flagged - agent values preserved, review needed.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("pbp_dir", nargs="?", default=None,
                    help="path to the PBP release dir (default: docs/.../pbp-benefits-<year>/)")
    ap.add_argument("--year", type=int, default=DEFAULT_PLAN_YEAR,
                    help=f"contract year to sync (default: {DEFAULT_PLAN_YEAR})")
    args = ap.parse_args()
    run(args.pbp_dir, plan_year=args.year)
