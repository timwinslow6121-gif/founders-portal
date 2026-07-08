"""Seed reviewed out-of-state BOB-name → plan-bucket aliases (Layer-1 follow-up A, OOS tail).

The tiny out-of-state book (SC where TimW/Anjana are licensed + paid; a few TX/WV/VA
former-NC members who moved and re-enrolled directly, AOR retained, we're not paid).
These are REAL, distinct plans with their own out-of-state CMS codes — seeded via
`seed_plan_buckets.py --states NC,SC,TX,WV,VA`. Their policies still need an alias where
the BOB plan_name carries no code (UHC) or is stale/wrong (Sheila's Aetna BOB says
"Medicare Select" but she's actually enrolled in H3931-101).

`state` stays on the policy — the eventual state FILTER (NC default) is what excludes
these from NC views; we do NOT lump them into a fake out-of-state bucket (an SC Humana
Gold Plus is a genuinely different plan than the NC one — different H-code + benefits).

Idempotent (append only if absent), read-only unless --apply. Re-run repair after.
The HealthSpring SC PDP (S5617-359) needs NO alias — its code is embedded in the BOB
plan_name, so it self-sorts once its bucket is seeded.

Usage:
  PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_out_of_state_aliases.py \
      --agency 1 [--apply]
"""
import argparse

from app import create_app
from app.extensions import db
from app.models import Plan

YEAR = 2026

# (carrier, target cms_plan_id) → raw BOB plan_name to add as an alias.
# Verified 2026-07-08 against the live orphan list + the CMS Landscape (states SC/TX/WV/VA).
_ALIASES = [
    ("UHC",   "H5322-040", "AARP Medicare Advantage from UHC SC-0005"),   # Curtis Lowder (SC)
    ("UHC",   "H2001-032", "UHC Dual Complete SC-S001"),                  # Susan Amato (SC)
    ("UHC",   "H4514-014", "AARP Medicare Advantage from UHC TX-001P"),   # Carolyn Murrey (TX)
    ("UHC",   "H2001-030", "UHC Dual Complete WV-S001"),                  # Susan Barr (WV)
    # Sheila Lawrence (VA) — BOB name is stale ("Aetna Medicare Select"); she is actually
    # enrolled in H3931-101 (Aetna Medicare Signature HMO-POS, VA). Alias the stale name.
    ("Aetna", "H3931-101", "Aetna Medicare Select (HMO-POS)"),
]


def _has_alias(plan, alias):
    existing = [plan.plan_name.strip().lower()] if plan.plan_name else []
    if plan.plan_name_aliases:
        existing += [a.strip().lower() for a in plan.plan_name_aliases.split(",")]
    return alias.strip().lower() in existing


def seed_aliases(agency_id, apply=False):
    counts = {"added": 0, "already": 0, "no_bucket": 0}
    missing = []
    for carrier, code, bob_name in _ALIASES:
        plan = Plan.query.filter_by(agency_id=agency_id, carrier=carrier,
                                    cms_plan_id=code, year=YEAR).first()
        if plan is None:
            counts["no_bucket"] += 1
            missing.append(f"{carrier} {code} ({bob_name})")
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
    # Dry-run: nothing of ours mutated outside `if apply:`, so no rollback (would
    # discard the caller's uncommitted work, e.g. test fixture buckets).
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
        print(f"[{mode}] out-of-state alias seed, agency {args.agency}:")
        print(f"  added:     {res['added']}")
        print(f"  already:   {res['already']}")
        print(f"  no_bucket: {res['no_bucket']}")
        for m in res["missing_buckets"]:
            print(f"    MISSING BUCKET (seed it first via seed_plan_buckets --states …): {m}")
        print("  Next: re-run scripts/repair_plan_id_linkage.py --agency 1 --year 2026 --apply")


if __name__ == "__main__":
    main()
