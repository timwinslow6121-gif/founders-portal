"""
Backfill Policy.plan_type to normalized values based on plan name + carrier.

Normalized plan_type values:
  MAPD     - Medicare Advantage with Part D
  MA       - Medicare Advantage without Part D (MA-only)
  DSNP     - Dual Special Needs Plan (D-SNP) - subset of MAPD
  CSNP     - Chronic Condition Special Needs Plan (C-SNP) - subset of MAPD
  MS       - Medicare Supplement (Medigap)
  PDP      - Prescription Drug Plan
  Dental   - Dental/Vision/Hearing
  (blank)  - Unknown / not yet classified

Run on VPS: ./venv/bin/python3 scripts/backfill_plan_types.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Policy

app = create_app()

# Exact plan_name → (plan_type, special_designation) mapping
# Built from Zoho CRM plan grid cross-referenced against DB plan names
PLAN_TYPE_MAP = {
    # ── UHC ──────────────────────────────────────────────────────────────
    "AARP Medicare Advantage from UHC NC-0015":         ("MAPD", None),
    "AARP Medicare Advantage from UHC NC-0021":         ("MAPD", None),
    "AARP Medicare Advantage from UHC NC-0009":         ("MAPD", None),
    "AARP Medicare Advantage from UHC SC-0006":         ("MAPD", None),
    "AARP Medicare Advantage Access from UHC NC-23":    ("MAPD", None),  # high-prem MAPD, not MA-only
    "UHC Dual Complete NC-S3":                          ("DSNP", "D-SNP"),
    "UHC Dual Complete NC-D001":                        ("DSNP", "D-SNP"),
    "UHC Dual Complete NC-V001":                        ("DSNP", "D-SNP"),
    "UHC Dual Complete NC-S001":                        ("DSNP", "D-SNP"),
    "UHC Complete Care NC-28":                          ("CSNP", "C-SNP"),
    "AARP MEDICARE SUPPLEMENT PLAN":                    ("MS",   None),
    "AARP Medicare Rx Preferred from UHC":              ("PDP",  None),

    # ── Humana ───────────────────────────────────────────────────────────
    "HUMANA GOLD PLUS HMO POS H1036-335":               ("MAPD", None),
    "HUMANA GOLD PLUS HMO H5619-152":                   ("MAPD", None),   # legacy plan, MAPD
    "HUMANA GOLD PLUS SNP-DE HMO H1036-331":            ("DSNP", "D-SNP"),
    "HUMANA DUAL INTEGRATED SNP-DE HMO H1396-001":      ("DSNP", "D-SNP"),
    "HUMANA USAA HONOR GIVEBACK PPO H5525-065":         ("MA",   "Part B Giveback"),
    "HUMANA USAA HONOR GIVEBACK PPO R0110-006":         ("MA",   "Part B Giveback"),
    "HUMANACHOICE PPO H5525-070":                       ("MAPD", None),
    "HUMANA VALUE RX PLAN PDP":                         ("PDP",  None),
    "HUMANA PREMIER RX PLAN PDP":                       ("PDP",  None),

    # ── BCBS ─────────────────────────────────────────────────────────────
    "Blue Medicare Enhanced (HMO-POS)":                 ("MAPD", None),
    "Blue Medicare Essential Plus (HMO-POS)":           ("MAPD", None),
    "Blue Medicare Freedom+ PPO":                       ("MA",   "Part B Giveback"),
    "Blue Medicare Medical Only (HMO-POS)":             ("MA",   "Part B Giveback"),
    "PPO Enhanced":                                     ("MAPD", None),
    "Healthy Blue + Medicare (H9147-001)":              ("MAPD", None),
    "MEDSUP G 2019":                                    ("MS",   None),

    # ── Dental ───────────────────────────────────────────────────────────
    "Dental Blue for Individuals PPO":                  ("Dental", None),
    "Dental Blue for Individuals PPO - Value 1500":     ("Dental", None),

    # ── HealthSpring ─────────────────────────────────────────────────────
    "2026_NC_H9725_015_HealthSpring Preferred Savings (HMO)": ("MAPD", None),

    # ── Aetna ────────────────────────────────────────────────────────────
    "Aetna Medicare Value Plus (HMO)":                  ("MAPD", None),
    "Aetna Medicare Signature (HMO)":                   ("MAPD", None),
    "Aetna Medicare Signature (PPO)":                   ("MAPD", None),
    "Aetna Medicare Dual (HMO D-SNP)":                  ("DSNP", "D-SNP"),
    "Aetna Medicare Full Dual Care (HMO D-SNP)":        ("DSNP", "D-SNP"),
    "CHOICE":                                           ("MAPD", None),
}

def run():
    with app.app_context():
        updated = 0
        skipped = 0
        unknown = []

        policies = Policy.query.all()
        for p in policies:
            name = (p.plan_name or "").strip()
            if name in PLAN_TYPE_MAP:
                new_type, _ = PLAN_TYPE_MAP[name]
                if p.plan_type != new_type:
                    print(f"  [{p.carrier}] {name!r:60s}  {repr(p.plan_type):20s} → {new_type!r}")
                    p.plan_type = new_type
                    updated += 1
            elif not name:
                skipped += 1
            else:
                if name not in [u[0] for u in unknown]:
                    unknown.append((name, p.carrier, p.plan_type))

        if unknown:
            print(f"\n⚠  Unrecognised plan names ({len(unknown)}) — NOT updated:")
            for name, carrier, ptype in unknown:
                print(f"  [{carrier}] {name!r} (current type: {repr(ptype)})")

        db.session.commit()
        print(f"\n✅  Updated {updated} policies. {skipped} had no plan name.")

if __name__ == "__main__":
    run()
