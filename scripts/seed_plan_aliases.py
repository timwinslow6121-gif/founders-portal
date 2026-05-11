"""
Seed plan_name_aliases, friendly_name, and fix Healthspring plan names.
Then resolve policies.plan_id for all existing policies via alias matching.

Run on VPS: ./venv/bin/python3 scripts/seed_plan_aliases.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import Plan, Policy

app = create_app()

# ---------------------------------------------------------------------------
# PLAN SEED DATA
# Each entry:  (carrier, cms_plan_id_or_None, plan_name_match_substr,
#               friendly_name, aliases_list)
#
# We match the existing Plan row by carrier + a substring of its current
# plan_name (enough to be unique), then set friendly_name + plan_name_aliases.
# For Healthspring we also fix the plan_name itself.
# ---------------------------------------------------------------------------

PLAN_UPDATES = [
    # ── UHC ──────────────────────────────────────────────────────────────
    {
        "carrier": "UHC", "match": "NC-0015",
        "friendly_name": "NC-0015",
        "aliases": [
            "AARP Medicare Advantage from UHC NC-0015",
        ],
    },
    {
        "carrier": "UHC", "match": "NC-0021",
        "friendly_name": "NC-0021",
        "aliases": [
            "AARP Medicare Advantage from UHC NC-0021",
        ],
    },
    {
        "carrier": "UHC", "match": "NC-0009",
        "friendly_name": "NC-0009",
        "aliases": [
            "AARP Medicare Advantage from UHC NC-0009",
        ],
    },
    {
        "carrier": "UHC", "match": "SC-0006",
        "friendly_name": "SC-0006",
        "aliases": [
            "AARP Medicare Advantage from UHC SC-0006",
        ],
    },
    {
        "carrier": "UHC", "match": "Access",
        "friendly_name": "NC-23 Access",
        "aliases": [
            "AARP Medicare Advantage Access from UHC NC-23",
        ],
    },
    {
        "carrier": "UHC", "match": "Dual Complete",
        "friendly_name": "Dual Complete D-SNP",
        "aliases": [
            "UHC Dual Complete NC-S3",
            "UHC Dual Complete NC-D001",
            "UHC Dual Complete NC-V001",
            "UHC Dual Complete NC-S001",
        ],
    },
    {
        "carrier": "UHC", "match": "Complete Care",
        "friendly_name": "Complete Care C-SNP",
        "aliases": [
            "UHC Complete Care NC-28",
        ],
    },
    {
        "carrier": "UHC", "match": "Supplement",
        "friendly_name": "Medigap Plan G",
        "aliases": [
            "AARP MEDICARE SUPPLEMENT PLAN",
        ],
    },
    {
        "carrier": "UHC", "match": "Rx Preferred",
        "friendly_name": "Rx Preferred PDP",
        "aliases": [
            "AARP Medicare Rx Preferred from UHC",
        ],
    },

    # ── Humana ───────────────────────────────────────────────────────────
    {
        "carrier": "Humana", "match": "H1036-335",
        "friendly_name": "Gold Plus H1036-335",
        "aliases": [
            "HUMANA GOLD PLUS HMO POS H1036-335",
        ],
    },
    {
        "carrier": "Humana", "match": "H5619-152",
        "friendly_name": "Gold Plus H5619-152",
        "aliases": [
            "HUMANA GOLD PLUS HMO H5619-152",
        ],
    },
    {
        "carrier": "Humana", "match": "H1036-331",
        "friendly_name": "Gold Plus SNP H1036-331",
        "aliases": [
            "HUMANA GOLD PLUS SNP-DE HMO H1036-331",
        ],
    },
    {
        "carrier": "Humana", "match": "H1396-001",
        "friendly_name": "Dual Integrated D-SNP",
        "aliases": [
            "HUMANA DUAL INTEGRATED SNP-DE HMO H1396-001",
        ],
    },
    {
        "carrier": "Humana", "match": "Honor",
        "friendly_name": "Honor Giveback PPO",
        "aliases": [
            "HUMANA USAA HONOR GIVEBACK PPO H5525-065",
            "HUMANA USAA HONOR GIVEBACK PPO R0110-006",
        ],
    },
    {
        "carrier": "Humana", "match": "Choice PPO",
        "friendly_name": "HumanaChoice PPO",
        "aliases": [
            "HUMANACHOICE PPO H5525-070",
        ],
    },
    {
        "carrier": "Humana", "match": "Value Rx",
        "friendly_name": "Value Rx PDP",
        "aliases": [
            "HUMANA VALUE RX PLAN PDP",
        ],
    },
    {
        "carrier": "Humana", "match": "Premier Rx",
        "friendly_name": "Premier Rx PDP",
        "aliases": [
            "HUMANA PREMIER RX PLAN PDP",
        ],
    },

    # ── BCBS ─────────────────────────────────────────────────────────────
    {
        "carrier": "BCBS", "match": "Enhanced",
        "friendly_name": "Blue Enhanced",
        "aliases": [
            "Blue Medicare Enhanced (HMO-POS)",
            "PPO Enhanced",
        ],
    },
    {
        "carrier": "BCBS", "match": "Essential Plus",
        "friendly_name": "Blue Essential Plus",
        "aliases": [
            "Blue Medicare Essential Plus (HMO-POS)",
        ],
    },
    {
        "carrier": "BCBS", "match": "Freedom",
        "friendly_name": "Blue Freedom+ PPO",
        "aliases": [
            "Blue Medicare Freedom+ PPO",
        ],
    },
    {
        "carrier": "BCBS", "match": "Medical Only",
        "friendly_name": "Blue Medical Only",
        "aliases": [
            "Blue Medicare Medical Only (HMO-POS)",
        ],
    },
    {
        "carrier": "BCBS", "match": "H9147-001",
        "friendly_name": "Healthy Blue D-SNP",
        "aliases": [
            "Healthy Blue + Medicare (H9147-001)",
        ],
    },
    {
        "carrier": "BCBS", "match": "Medigap",
        "friendly_name": "Medigap Plan G",
        "aliases": [
            "MEDSUP G 2019",
        ],
    },
    {
        "carrier": "BCBS", "match": "Dental Blue",
        "friendly_name": "Dental Blue PPO",
        "aliases": [
            "Dental Blue for Individuals PPO",
            "Dental Blue for Individuals PPO - Value 1500",
        ],
    },

    # ── Aetna ────────────────────────────────────────────────────────────
    {
        "carrier": "Aetna", "match": "Value Plus",
        "friendly_name": "Aetna Value Plus HMO",
        "aliases": [
            "Aetna Medicare Value Plus (HMO)",
        ],
    },
    {
        "carrier": "Aetna", "match": "Signature HMO",
        "friendly_name": "Aetna Signature HMO",
        "aliases": [
            "Aetna Medicare Signature (HMO)",
            "CHOICE",
        ],
    },
    {
        "carrier": "Aetna", "match": "Signature PPO",
        "friendly_name": "Aetna Signature PPO",
        "aliases": [
            "Aetna Medicare Signature (PPO)",
        ],
    },
    {
        "carrier": "Aetna", "match": "Dual HMO",
        "friendly_name": "Aetna Dual D-SNP",
        "aliases": [
            "Aetna Medicare Dual (HMO D-SNP)",
            "Aetna Medicare Full Dual Care (HMO D-SNP)",
        ],
    },
]

# Healthspring: delete bad Cigna-named plans, insert correct one
HEALTHSPRING_FIX = {
    "delete_name_contains": ["Cigna"],
    "new_plan": {
        "carrier": "Healthspring",
        "plan_name": "HealthSpring Preferred Savings HMO",
        "friendly_name": "HealthSpring Preferred Savings",
        "year": 2026,
        "plan_type": "mapd",
        "cms_plan_id": "H9725-015",
        "plan_name_aliases": "2026_NC_H9725_015_HealthSpring Preferred Savings (HMO)",
        "status": "current",
        "is_commissionable": True,
    },
}


def _find_plan(carrier, match_substr, agency_id):
    """Find a Plan row by carrier and a unique substring of its plan_name."""
    return (Plan.query
            .filter_by(carrier=carrier, agency_id=agency_id)
            .filter(Plan.plan_name.ilike(f"%{match_substr}%"))
            .first())


def run():
    with app.app_context():
        # Determine agency_id — use the one that has plans
        agency_id = db.session.execute(
            db.text("SELECT agency_id FROM plans LIMIT 1")
        ).scalar()
        if not agency_id:
            print("No plans found. Exiting.")
            return

        updated_plans = 0

        # ── Fix Healthspring ──────────────────────────────────────────────
        bad = (Plan.query.filter_by(carrier="Healthspring", agency_id=agency_id)
               .filter(Plan.plan_name.ilike("%Cigna%")).all())
        for p in bad:
            print(f"  Deleting bad Healthspring plan: {p.plan_name!r}")
            db.session.delete(p)
        db.session.flush()

        existing_hs = Plan.query.filter_by(
            carrier="Healthspring", agency_id=agency_id,
            cms_plan_id="H9725-015"
        ).first()
        if not existing_hs:
            hs = Plan(agency_id=agency_id, **HEALTHSPRING_FIX["new_plan"])
            db.session.add(hs)
            print(f"  Created HealthSpring Preferred Savings HMO (H9725-015)")
            updated_plans += 1
        else:
            print(f"  HealthSpring H9725-015 already exists, skipping create")

        # ── Apply aliases + friendly names ────────────────────────────────
        for entry in PLAN_UPDATES:
            plan = _find_plan(entry["carrier"], entry["match"], agency_id)
            if not plan:
                print(f"  ⚠  NOT FOUND: [{entry['carrier']}] match={entry['match']!r}")
                continue
            plan.friendly_name = entry["friendly_name"]
            plan.plan_name_aliases = ",".join(entry["aliases"])
            print(f"  ✓  [{entry['carrier']}] {plan.plan_name!r} → friendly={entry['friendly_name']!r}")
            updated_plans += 1

        db.session.flush()

        # ── Resolve policies.plan_id via alias matching ───────────────────
        # Build alias → plan_id lookup
        alias_map = {}  # raw BOB name (lower) → plan_id
        for p in Plan.query.filter_by(agency_id=agency_id).all():
            if p.plan_name_aliases:
                for alias in p.plan_name_aliases.split(","):
                    alias = alias.strip()
                    if alias:
                        alias_map[alias.lower()] = p.id
            # Also match on plan_name itself
            if p.plan_name:
                alias_map[p.plan_name.lower()] = p.id

        resolved = 0
        unresolved = set()
        for policy in Policy.query.filter_by(agency_id=agency_id).all():
            name = (policy.plan_name or "").strip().lower()
            if name in alias_map:
                new_id = alias_map[name]
                if policy.plan_id != new_id:
                    policy.plan_id = new_id
                    resolved += 1
            elif name:
                unresolved.add(policy.plan_name)

        if unresolved:
            print(f"\n⚠  Unresolved policy plan_names ({len(unresolved)}) — plan_id left NULL:")
            for n in sorted(unresolved):
                print(f"  {n!r}")

        db.session.commit()
        print(f"\n✅  Updated {updated_plans} plans. Resolved plan_id on {resolved} policies.")


if __name__ == "__main__":
    run()
