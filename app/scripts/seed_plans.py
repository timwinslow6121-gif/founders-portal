"""
seed_plans.py

Seeds the plans table from known policy data.
Run once: flask shell < app/scripts/seed_plans.py
Or: from app.scripts.seed_plans import seed; seed()

Sources: active policies BOB data + March 2026 commission statements.
Plan years reflect the year the plan is currently active (2026).
Commission rates from agent_carrier_contracts / known CMS rates.
"""

from app.extensions import db
from app.models import Plan


AGENCY_ID   = 1
CREATED_BY  = 1  # Tim (admin)
YEAR        = 2026


PLANS = [

    # -------------------------------------------------------------------------
    # AETNA
    # -------------------------------------------------------------------------
    dict(
        carrier="Aetna", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="Aetna Medicare Eagle PPO",
        cms_plan_id="H5521-284",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Aetna Medicare Eagle PPO",
    ),
    dict(
        carrier="Aetna", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Aetna Medicare Assure HMO",
        cms_plan_id="H5521-244",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Aetna Medicare Assure HMO",
    ),
    dict(
        carrier="Aetna", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Aetna Medicare Value Plus HMO",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Aetna Medicare Value Plus (HMO)",
    ),
    dict(
        carrier="Aetna", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Aetna Medicare Dual HMO D-SNP",
        is_dsnp=True,
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Aetna Medicare Dual (HMO D-SNP),Aetna Medicare Full Dual Care (HMO D-SNP)",
    ),
    dict(
        carrier="Aetna", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Aetna Medicare Signature HMO",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Aetna Medicare Signature (HMO),Aetna Medicare Signature (PPO)",
    ),

    # -------------------------------------------------------------------------
    # BCBS
    # -------------------------------------------------------------------------
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="Blue Medicare Freedom+ PPO",
        cms_plan_id="H3894-009",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Blue Medicare Freedom+ PPO",
    ),
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Blue Medicare Plus HMO",
        cms_plan_id="H3894-006",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Blue Medicare Plus HMO",
    ),
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="hmo_pos",
        plan_name="Blue Medicare Medical Only HMO-POS",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Blue Medicare Medical Only (HMO-POS)",
    ),
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="hmo_pos",
        plan_name="Blue Medicare Enhanced HMO-POS",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Blue Medicare Enhanced (HMO-POS)",
    ),
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="hmo_pos",
        plan_name="Blue Medicare Essential Plus HMO-POS",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Blue Medicare Essential Plus (HMO-POS)",
    ),
    dict(
        carrier="BCBS", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Healthy Blue + Medicare HMO D-SNP",
        cms_plan_id="H9147-001",
        is_dsnp=True,
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Healthy Blue + Medicare (H9147-001)",
    ),
    # BCBS Medigap — Plan G (2019 issue year pool)
    dict(
        carrier="BCBS", year=YEAR, plan_type="medigap",
        plan_name="Blue Medicare Supplement Plan G",
        plan_letter="G",
        external_id="MedSupp G 2019",
        status="current",
        service_area="NC",
        comm_type="percent_premium", comm_initial=0.20, comm_renewal=0.20,
        is_commissionable=True,
        plan_name_aliases="MedSupp G 2019,MEDSUP G 2019",
        comm_notes="20% of premium. Issue year 2019 pool — rates differ from newer issue years.",
    ),
    # BCBS Dental
    dict(
        carrier="BCBS", year=YEAR, plan_type="dvh",
        plan_name="Dental Blue for Individuals PPO",
        status="current",
        service_area="NC",
        comm_type="percent_premium", comm_initial=0.20, comm_renewal=0.20,
        is_commissionable=True,
        plan_name_aliases="Dental Blue for Individuals PPO,Dental Blue for Individuals PPO - Value 1500",
    ),

    # -------------------------------------------------------------------------
    # DEVOTED
    # -------------------------------------------------------------------------
    dict(
        carrier="Devoted", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Devoted Health Plus HMO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Devoted Health Plus HMO",
    ),
    dict(
        carrier="Devoted", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Devoted Health Value HMO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Devoted Health Value HMO",
    ),

    # -------------------------------------------------------------------------
    # HEALTHSPRING (Cigna)
    # -------------------------------------------------------------------------
    dict(
        carrier="Healthspring", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="Cigna Healthspring Premier PPO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Cigna Healthspring Premier PPO",
    ),
    dict(
        carrier="Healthspring", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Cigna Healthspring Achieve HMO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Cigna Healthspring Achieve HMO",
    ),

    # -------------------------------------------------------------------------
    # HUMANA
    # -------------------------------------------------------------------------
    dict(
        carrier="Humana", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="Humana Choice PPO",
        cms_plan_id="H5525-034",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Humana Choice PPO",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Humana Gold Plus HMO H1036-335",
        cms_plan_id="H1036-335",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="HUMANA GOLD PLUS HMO POS H1036-335,Humana Gold Plus HMO",
        comm_notes="2026 successor to H1036-291. Members from 291 auto-transitioned at end of 2025.",
    ),
    dict(
        carrier="Humana", year=2025, plan_type="mapd", plan_subtype="hmo",
        plan_name="Humana Gold Plus HMO H1036-291",
        cms_plan_id="H1036-291",
        status="sunset",
        auto_transitioned=True,
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="H1036-291",
        comm_notes="Terminated end of 2025. Members auto-moved to H1036-335.",
    ),
    dict(
        carrier="Humana", year=2023, plan_type="mapd", plan_subtype="hmo",
        plan_name="Humana Gold Plus HMO H1036-137",
        cms_plan_id="H1036-137",
        status="legacy",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="H1036-137",
        comm_notes="Legacy plan. Humana calls these legacy — still active but benefits degraded. Superseded by H1036-291 then H1036-335.",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="Humana Honor PPO",
        cms_plan_id="H5525-065",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="Humana Honor,HUMANA USAA HONOR GIVEBACK PPO H5525-065,HUMANA USAA HONOR GIVEBACK PPO R0110-006",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Humana Gold Plus SNP-DE HMO H1036-331",
        cms_plan_id="H1036-331",
        is_dsnp=True,
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="HUMANA GOLD PLUS SNP-DE HMO H1036-331",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="Humana Dual Integrated SNP-DE HMO H1396-001",
        cms_plan_id="H1396-001",
        is_dsnp=True,
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="HUMANA DUAL INTEGRATED SNP-DE HMO H1396-001",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="pdp",
        plan_name="Humana Value Rx Plan PDP",
        status="current",
        service_area="National",
        monthly_premium=None,
        comm_type="pmpm", comm_initial=3.00, comm_renewal=3.00,
        is_commissionable=True,
        plan_name_aliases="HUMANA VALUE RX PLAN PDP",
    ),
    dict(
        carrier="Humana", year=YEAR, plan_type="pdp",
        plan_name="Humana Premier Rx Plan PDP",
        status="current",
        service_area="National",
        monthly_premium=None,
        comm_type="pmpm", comm_initial=3.00, comm_renewal=3.00,
        is_commissionable=True,
        plan_name_aliases="HUMANA PREMIER RX PLAN PDP",
    ),

    # -------------------------------------------------------------------------
    # UHC
    # -------------------------------------------------------------------------
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="AARP MedicareComplete Insured HMO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="AARP MedicareComplete Insured HMO",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="ppo",
        plan_name="AARP MedicareComplete Choice PPO",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="AARP MedicareComplete Choice PPO",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="UHC Dual Complete HMO D-SNP",
        is_dsnp=True,
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="UHC Dual Complete,UHC Dual Complete NC-S3,UHC Dual Complete NC-D001,UHC Dual Complete NC-V001,UHC Dual Complete NC-S001",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="AARP Medicare Advantage from UHC",
        status="current",
        service_area="Western NC / SC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="AARP Medicare Advantage from UHC NC-0015,AARP Medicare Advantage from UHC NC-0021,AARP Medicare Advantage from UHC NC-0009,AARP Medicare Advantage from UHC SC-0006",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="UHC Complete Care",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="UHC Complete Care NC-28",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="mapd", plan_subtype="hmo",
        plan_name="AARP Medicare Advantage Access from UHC",
        status="current",
        service_area="Western NC",
        monthly_premium=0.0,
        comm_type="pmpm", comm_initial=22.00, comm_renewal=15.00,
        is_commissionable=True,
        plan_name_aliases="AARP Medicare Advantage Access from UHC NC-23",
    ),
    dict(
        carrier="UHC", year=YEAR, plan_type="pdp",
        plan_name="AARP Medicare Rx Preferred from UHC",
        status="current",
        service_area="National",
        monthly_premium=None,
        comm_type="pmpm", comm_initial=3.00, comm_renewal=3.00,
        is_commissionable=True,
        plan_name_aliases="AARP Medicare Rx Preferred from UHC",
    ),
    # UHC Medigap
    dict(
        carrier="UHC", year=YEAR, plan_type="medigap",
        plan_name="AARP Medicare Supplement Plan G",
        plan_letter="G",
        external_id="G02",
        status="current",
        service_area="NC",
        comm_type="percent_premium", comm_initial=0.20, comm_renewal=0.20,
        is_commissionable=True,
        plan_name_aliases="AARP MEDICARE SUPPLEMENT PLAN,AARP Medicare Supplement Plan",
        comm_notes="UHC internal contract G02. 20% of premium.",
    ),
]


def seed():
    created = 0
    skipped = 0

    for p in PLANS:
        # Check for existing by carrier + plan_name + year (cms_plan_id may be null for some)
        existing = Plan.query.filter_by(
            agency_id=AGENCY_ID,
            carrier=p["carrier"],
            plan_name=p["plan_name"],
            year=p["year"],
        ).first()

        if existing:
            skipped += 1
            continue

        plan = Plan(
            agency_id        = AGENCY_ID,
            created_by_id    = CREATED_BY,
            is_dsnp          = p.pop("is_dsnp", False),
            is_csnp          = p.pop("is_csnp", False),
            is_5star         = p.pop("is_5star", False),
            auto_transitioned= p.pop("auto_transitioned", False),
            is_commissionable= p.pop("is_commissionable", True),
            **p,
        )
        db.session.add(plan)
        created += 1

    db.session.commit()

    # Wire up successor chain after all plans exist
    _link("H1036-137", "H1036-291")
    _link("H1036-291", "H1036-335")
    db.session.commit()

    print(f"Seeded {created} plans, skipped {skipped} existing.")


def _link(from_id, to_id):
    """Set successor_plan_id from one CMS plan ID to another."""
    from_plan = Plan.query.filter_by(agency_id=AGENCY_ID, cms_plan_id=from_id).first()
    to_plan   = Plan.query.filter_by(agency_id=AGENCY_ID, cms_plan_id=to_id).first()
    if from_plan and to_plan:
        from_plan.successor_plan_id = to_plan.id


if __name__ == "__main__":
    seed()
