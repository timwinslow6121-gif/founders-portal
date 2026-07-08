"""Seed reviewed UHC BOB-name → plan-bucket aliases (Layer-1 follow-up A).

UHC BOB rows carry a marketing plan name (e.g. "AARP Medicare Advantage from UHC
NC-0017") but NO CMS contract code, so find_plan_bucket can't match them by code —
it falls to _alias_hit, which does an EXACT lowercase match against a bucket's
plan_name / plan_name_aliases. The seeded bucket's plan_name has a trailing form
suffix ("… NC-0017 (PPO)") that differs from the raw BOB string, so these rows stay
orphaned until the raw BOB name is added as an alias on the right bucket.

This maps each distinct orphaned UHC BOB plan_name to its target bucket's
cms_plan_id (matched by the NC marketing code), verified 2026-07-08 against the
live orphan list + the seeded UHC buckets. Idempotent: appends an alias only if
absent. Read-only unless --apply. After running, re-run repair_plan_id_linkage.py.

NOT included (need different fixes, see BACKLOG Follow-ups B/C):
  - medigap "AARP MEDICARE SUPPLEMENT PLAN[/ G/ N]" — find_plan_bucket's medigap
    branch matches by (plan_letter, year=PERPETUAL) and never consults aliases;
    the medigap buckets are also stored at year=2026 not PERPETUAL. Needs the
    medigap-branch fix, not an alias.
  - out-of-state / non-MA (SC/TX/WV plans, DVH 1000, Group MA) — no NC bucket by
    design; left orphaned (real members, but out of the NC-MA bucket set).

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_uhc_aliases.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

CARRIER = "UHC"
YEAR = 2026

# BOB plan_name (raw, as it appears on the policy) → target bucket cms_plan_id.
_ALIASES = {
    "AARP Medicare Advantage Patriot No Rx NC-MA02": "H5253-040",
    "AARP Medicare Advantage from UHC NC-0017":      "H2406-098",
    "AARP Medicare Advantage from UHC NC-0016":      "H2406-034",
    "AARP Medicare Advantage Giveback from UHC NC-14":"H5253-110",
    "AARP Medicare Advantage from UHC NC-0022":      "H5253-038",
    "AARP Medicare Advantage from UHC NC-24":        "H5253-185",
    "AARP Medicare Advantage from UHC NC-0001":      "H2001-090",
    "UHC Complete Care NC-25":                       "H5253-186",
    "AARP Medicare Advantage from UHC NC-26":        "H5253-187",
    "AARP Medicare Advantage from UHC NC-0004":      "H2001-102",
    "UHC Dual Complete NC-S2":                       "H1889-034",
    "AARP Medicare Rx Saver from UHC":               "S5921-353",
}


def _has_alias(plan, alias):
    existing = [plan.plan_name.strip().lower()] if plan.plan_name else []
    if plan.plan_name_aliases:
        existing += [a.strip().lower() for a in plan.plan_name_aliases.split(",")]
    return alias.strip().lower() in existing


def seed_aliases(agency_id, apply=False):
    counts = {"added": 0, "already": 0, "no_bucket": 0}
    missing = []
    for bob_name, code in _ALIASES.items():
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=CARRIER,
                                    cms_plan_id=code, year=YEAR).first()
        if plan is None:
            counts["no_bucket"] += 1
            missing.append(f"{code} ({bob_name})")
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
    # Dry-run: aliases are only mutated inside `if apply:` above, so there is nothing
    # of ours to undo. Do NOT rollback unconditionally — that would also discard the
    # caller's own uncommitted work (e.g. a test that flush()'d fixture buckets).
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
        print(f"[{mode}] UHC alias seed, agency {args.agency}:")
        print(f"  added:     {res['added']}")
        print(f"  already:   {res['already']}")
        print(f"  no_bucket: {res['no_bucket']}")
        for m in res["missing_buckets"]:
            print(f"    MISSING BUCKET: {m}")
        print("  Next: re-run scripts/repair_plan_id_linkage.py --agency 1 --year 2026 --apply")


if __name__ == "__main__":
    main()
