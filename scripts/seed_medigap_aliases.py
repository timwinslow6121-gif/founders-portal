"""Seed reviewed Medigap BOB-name → medigap-bucket aliases.

Some medigap policies carry a carrier code as the plan name/type that has no
extractable letter and doesn't match the bucket's descriptive name — e.g. UHC writes
"AARPMODMEDSUP" (AARP Modernized Medicare Supplement) for its Plan G medigap. The
find_plan_bucket medigap branch tries the alias path for no-letter names, so adding
"AARPMODMEDSUP" as an alias on the UHC Plan G bucket links those ~51 policies.

Medigap buckets are keyed by (carrier, plan_letter) — NOT cms_plan_id (NULL) — so this
targets by letter. Idempotent; read-only unless --apply. Run repair after.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_medigap_aliases.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026

# (carrier, plan_letter, raw BOB string to alias onto that medigap bucket).
_ALIASES = [
    ("UHC", "G", "AARPMODMEDSUP"),   # UHC's code for its AARP Plan G medigap (~51 policies)
]


def _has_alias(plan, alias):
    existing = [plan.plan_name.strip().lower()] if plan.plan_name else []
    if plan.plan_name_aliases:
        existing += [a.strip().lower() for a in plan.plan_name_aliases.split(",")]
    return alias.strip().lower() in existing


def seed_aliases(agency_id, apply=False):
    counts = {"added": 0, "already": 0, "no_bucket": 0}
    missing = []
    for carrier, letter, bob_name in _ALIASES:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    plan_letter=letter, year=YEAR).first()
        if plan is None:
            counts["no_bucket"] += 1
            missing.append(f"{carrier} Plan {letter} ({bob_name})")
            continue
        if _has_alias(plan, bob_name):
            counts["already"] += 1
            continue
        counts["added"] += 1
        if apply:
            plan.plan_name_aliases = (
                bob_name if not plan.plan_name_aliases
                else f"{plan.plan_name_aliases},{bob_name}")
    counts["missing_buckets"] = missing
    if apply:
        db.session.commit()
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agency", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    app = create_app()
    with app.app_context():
        res = seed_aliases(args.agency, apply=args.apply)
        mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
        print(f"[{mode}] medigap alias seed, agency {args.agency}:")
        print(f"  added:     {res['added']}")
        print(f"  already:   {res['already']}")
        print(f"  no_bucket: {res['no_bucket']}")
        for m in res["missing_buckets"]:
            print(f"    MISSING BUCKET: {m}")
        print("  Next: re-run scripts/repair_plan_id_linkage.py --agency 1 --year 2026 --apply")


if __name__ == "__main__":
    main()
