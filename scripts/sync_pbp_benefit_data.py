"""
Sync copay benefit data from CMS Plan Benefit Package (PBP) flat text files into the plans table.

SOURCE FILES (tab-delimited):
  docs/Medicare Landscape Files/pbp-benefits-2026/pbp_b4_emerg_urgent.txt  → ER copay
  docs/Medicare Landscape Files/pbp-benefits-2026/pbp_b7_health_prof.txt   → PCP + specialist copay

WHAT IT UPDATES:
  - pcp_copay        (b7a = Primary Care Physician)
  - specialist_copay (b7c = Outpatient Hospital Specialist — what SOB shows as "Specialist")
  - er_copay         (b4a = Emergency Room, waived if admitted)

WHAT IT REPORTS (scripts/pbp_sync_report.txt):
  - Plans updated with old → new values
  - Plans with cms_plan_id not found in PBP files (wrong ID or PDP-only plans)

Run on VPS: ./venv/bin/python3 scripts/sync_pbp_benefit_data.py [optional/path/to/pbp-benefits-dir]
"""
import sys, os, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

PLAN_YEAR = 2026

DEFAULT_PBP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "Medicare Landscape Files", "pbp-benefits-2026",
)

# ---------------------------------------------------------------------------
# Load PBP flat files into dicts keyed by (hnumber, plan_id)
# ---------------------------------------------------------------------------

def _load_tsv(filepath):
    """Load a tab-delimited PBP file. Returns list of dicts."""
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)


def _build_lookup(rows, segment="0"):
    """
    Build lookup dict: (hnumber_upper, plan_id_str) → row.
    Uses segment_id=0 (base segment present for all plans including multi-segment).
    plan_id_str is the raw value from the file, e.g. "117" (not zero-padded).
    """
    lookup = {}
    for row in rows:
        if row.get("segment_id", "").strip() != segment:
            continue
        key = (
            row["pbp_a_hnumber"].strip().upper(),
            row["pbp_a_plan_identifier"].strip(),
        )
        lookup[key] = row
    return lookup


def _parse_cms_plan_id(cms_plan_id):
    """
    "H5253-117" → ("H5253", "117")  (plan_id stripped of leading zeros)
    "H1036-335" → ("H1036", "335")
    Returns None if unparseable.
    """
    parts = cms_plan_id.strip().upper().split("-")
    if len(parts) < 2:
        return None
    contract = parts[0]
    plan_id  = str(int(parts[1]))   # strips leading zeros: "034" → "34"
    return (contract, plan_id)


# ---------------------------------------------------------------------------
# Copay formatting
# ---------------------------------------------------------------------------

def _fmt_amount(val_str):
    """'150.00' → '$150', '35.50' → '$35.50', '0.00' → '$0'"""
    try:
        val = float(val_str)
    except (ValueError, TypeError):
        return None
    if val == int(val):
        return f"${int(val)}"
    return f"${val:.2f}"


def _extract_copay(row, yn_col, min_col, max_col, coins_yn_col=None, coins_min_col=None):
    """
    Extract a copay display string from PBP row columns.
    Returns None if the benefit doesn't apply or data is missing.
    """
    yn = row.get(yn_col, "").strip()
    if yn == "2":   # copay not applicable
        # Check coinsurance instead
        if coins_yn_col and row.get(coins_yn_col, "").strip() == "1":
            pct_min = row.get(coins_min_col, "").strip()
            if pct_min:
                try:
                    return f"{int(float(pct_min))}%"
                except ValueError:
                    pass
        return "$0"

    lo_str = row.get(min_col, "").strip()
    hi_str = row.get(max_col, "").strip()
    lo = _fmt_amount(lo_str)
    hi = _fmt_amount(hi_str)

    if lo is None:
        return None
    if lo == hi or not hi:
        return lo
    return f"{lo}-{hi}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(pbp_dir=None):
    pbp_dir = pbp_dir or DEFAULT_PBP_DIR

    b4_path = os.path.join(pbp_dir, "pbp_b4_emerg_urgent.txt")
    b7_path = os.path.join(pbp_dir, "pbp_b7_health_prof.txt")

    for p in (b4_path, b7_path):
        if not os.path.exists(p):
            print(f"❌  File not found: {p}")
            return

    print(f"Loading PBP flat files from: {pbp_dir}")
    b4_lookup = _build_lookup(_load_tsv(b4_path))
    b7_lookup = _build_lookup(_load_tsv(b7_path))
    print(f"  b4 (emergency): {len(b4_lookup)} plans")
    print(f"  b7 (health prof): {len(b7_lookup)} plans\n")

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

        updates = {}   # plan.id → {field: (old, new)}
        missing = []   # plans where cms_plan_id not in PBP file (PDP-only or bad ID)

        for plan in db_plans:
            if not plan.cms_plan_id:
                continue

            key = _parse_cms_plan_id(plan.cms_plan_id)
            if not key:
                missing.append((plan, "unparseable cms_plan_id"))
                continue

            b4_row = b4_lookup.get(key)
            b7_row = b7_lookup.get(key)

            if not b4_row and not b7_row:
                missing.append((plan, "not in PBP files — likely PDP-only"))
                continue

            changes = {}

            # PCP copay (b7a)
            if b7_row:
                pcp = _extract_copay(
                    b7_row,
                    yn_col="pbp_b7a_copay_yn",
                    min_col="pbp_b7a_copay_amt_mc_min",
                    max_col="pbp_b7a_copay_amt_mc_max",
                    coins_yn_col="pbp_b7a_coins_yn",
                    coins_min_col="pbp_b7a_coins_pct_mc_min",
                )
                if pcp is not None and pcp != plan.pcp_copay:
                    changes["pcp_copay"] = (plan.pcp_copay, pcp)
                    plan.pcp_copay = pcp

                # Specialist copay (b7c = outpatient hospital specialist — what SOB shows)
                spec = _extract_copay(
                    b7_row,
                    yn_col="pbp_b7c_copay_yn",
                    min_col="pbp_b7c_copay_mc_amt_min",
                    max_col="pbp_b7c_copay_mc_amt_max",
                    coins_yn_col="pbp_b7c_coins_yn",
                    coins_min_col="pbp_b7c_coins_pct_mc_min",
                )
                if spec is not None and spec != plan.specialist_copay:
                    changes["specialist_copay"] = (plan.specialist_copay, spec)
                    plan.specialist_copay = spec

            # ER copay (b4a)
            if b4_row:
                er = _extract_copay(
                    b4_row,
                    yn_col="pbp_b4a_copay_yn",
                    min_col="pbp_b4a_copay_amt_mc_min",
                    max_col="pbp_b4a_copay_amt_mc_max",
                    coins_yn_col="pbp_b4a_coins_yn",
                    coins_min_col="pbp_b4a_coins_pct_mc_min",
                )
                if er is not None and er != plan.er_copay:
                    changes["er_copay"] = (plan.er_copay, er)
                    plan.er_copay = er

            if changes:
                updates[plan.id] = {"plan": plan, "changes": changes}

        db.session.commit()

        # --- Report ---
        lines = [
            f"PBP Flat File Sync Report — {PLAN_YEAR}",
            f"Source: {os.path.basename(pbp_dir)}",
            "=" * 65, "",
            f"UPDATED ({len(updates)} plans):",
        ]
        if updates:
            for entry in sorted(updates.values(), key=lambda e: (e["plan"].carrier, e["plan"].plan_name)):
                p = entry["plan"]
                lines.append(f"\n  {p.carrier} | {p.cms_plan_id} | {p.friendly_name or p.plan_name}")
                for field, (old, new) in entry["changes"].items():
                    lines.append(f"    {field}: {old!r} → {new!r}")
        else:
            lines.append("  (no changes — DB already up to date)")

        lines += ["", "=" * 65, "",
                  f"NOT FOUND IN PBP FILES ({len(missing)} plans):"]
        for (p, reason) in missing:
            lines.append(f"  {(p.cms_plan_id or 'NO_ID'):15s}  {p.carrier:15s}  {p.friendly_name or p.plan_name}  [{reason}]")

        report_path = os.path.join(os.path.dirname(__file__), "pbp_sync_report.txt")
        with open(report_path, "w") as f:
            f.write("\n".join(lines))

        print(f"✅  Updated {len(updates)} plans.")
        print(f"⚠️   {len(missing)} plans not found in PBP files (see report).")
        print(f"📄  Report: scripts/pbp_sync_report.txt")

        if updates:
            print()
            for entry in sorted(updates.values(), key=lambda e: (e["plan"].carrier, e["plan"].plan_name)):
                p = entry["plan"]
                print(f"  ✓ {p.carrier} {p.cms_plan_id} — {', '.join(entry['changes'].keys())}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
