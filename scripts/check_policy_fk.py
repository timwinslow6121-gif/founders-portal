"""READ-ONLY: what references a policy row? (to safely re-point payments + delete
the commission-side Humana policy). Checks FKs to policies.id + payment identity."""
import sqlalchemy as sa
from app import create_app
from app.extensions import db
from app.models import PolicyPayment

COMM = 5923   # Arthur Hodge commission-side policy
BOB = 11026   # Arthur Hodge BOB-side policy


def main():
    app = create_app()
    with app.app_context():
        print("PolicyPayments on comm pol %s:" % COMM,
              PolicyPayment.query.filter_by(policy_id=COMM).count())
        print("PolicyPayments on BOB pol %s:" % BOB,
              PolicyPayment.query.filter_by(policy_id=BOB).count())

        insp = sa.inspect(db.engine)
        print("\nTables with a FK to policies.id:")
        for t in insp.get_table_names():
            for fk in insp.get_foreign_keys(t):
                if fk.get("referred_table") == "policies":
                    print("  %s.%s -> policies.%s ondelete=%s"
                          % (t, fk["constrained_columns"], fk["referred_columns"],
                             fk.get("options", {}).get("ondelete")))

        print("\nComm-policy payment identity:")
        for x in PolicyPayment.query.filter_by(policy_id=COMM).all():
            print("  payment %s mbi=%r carrier_member_id=%r amt=%s"
                  % (x.id, getattr(x, "mbi", None), getattr(x, "carrier_member_id", None),
                     x.paid_amount))


if __name__ == "__main__":
    main()
