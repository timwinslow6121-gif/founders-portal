"""Backfill Bradley/Clark policy effective dates (so their AOR interval derives) +
correct Clark's SilverScript Choice PDP mislabel. Dry-run default; --apply.

Tim-provided (2026-07-17):
  Frederick Bradley (cust 1635, policy 529): Aetna Medicare Dual HMO D-SNP, coverage eff 2026-01-01. Plan already correct.
  Elizabeth Clark (cust 1641, policy 535): SilverScript CHOICE PDP (stored wrong as 'CHOICE' MAPD),
    coverage eff 2025-01-01 → fix plan_type MAPD→pdp, plan_name→'SilverScript Choice (PDP)', plan_id→232 (the canonical bucket).
"""
import sys
from datetime import date
from app import create_app
from app.extensions import db
from app.models import Policy, Plan

SILVERSCRIPT_CHOICE_PLAN_ID = 232  # 'SilverScript Choice (PDP)', S5601-016, current


def main(apply):
    app = create_app()
    with app.app_context():
        print(f"{'APPLY' if apply else 'DRY-RUN'} — Bradley/Clark fixes\n")

        # Bradley: just the eff date
        b = db.session.get(Policy, 529)
        if b and b.customer_id == 1635:
            print(f"  Bradley policy 529 | {b.plan_name} [{b.plan_type}] | eff {b.effective_date} -> 2026-01-01")
            if apply:
                b.effective_date = date(2026, 1, 1)
        else:
            print("  ⚠ Bradley policy 529 not found / wrong customer — SKIP")

        # Clark: eff date + PDP correction + plan link
        c = db.session.get(Policy, 535)
        pl = db.session.get(Plan, SILVERSCRIPT_CHOICE_PLAN_ID)
        if c and c.customer_id == 1641 and pl:
            print(f"  Clark policy 535 | {c.plan_name!r} [{c.plan_type}] | eff {c.effective_date} "
                  f"-> eff 2025-01-01, plan_name '{pl.plan_name}', type pdp, plan_id {pl.id}")
            if apply:
                c.effective_date = date(2025, 1, 1)
                c.plan_type = "pdp"
                c.plan_name = pl.plan_name
                c.plan_id = pl.id
        else:
            print("  ⚠ Clark policy 535 / plan 232 not found — SKIP")

        if apply:
            db.session.commit()
            print("\nCOMMITTED.")
        else:
            db.session.rollback()
            print("\nDRY-RUN — nothing written.")


if __name__ == "__main__":
    main("--apply" in sys.argv)
