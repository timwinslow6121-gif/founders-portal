"""Seed UHC Writing Agent IDs onto AgentCarrierContract.id_value.

UHC attributes commission rows by Writing Agent ID (raw col 4), NOT the writing-
agent NAME (which is 'FOUNDERS INSURANCE AGENCY, LLC' for Rebekah and others). The
parser maps that ID -> portal agent via these contract id_values. Idempotent.

Run on the VPS: ./venv/bin/python3 scripts/seed_uhc_writing_ids.py
"""
from app import create_app
from app.extensions import db
from app.models import AgentCarrierContract, User

# Confirmed against the May 2026 raw statement (col 4 Writing Agent ID -> agent).
# Cyndi & Don are retired (roll up to Brian later via apply_rollup) but still need
# their ID mapped so the parser resolves their rows to their real name first.
UHC_WRITING_IDS = {
    "Timothy Winslow": "6337213",
    "Mike Lauzurique": "6540381",
    "Rebekah Long": "6435806",      # writes as FOUNDERS INSURANCE AGENCY, LLC
    "Brian Freeman": "6515098",
    "Justin Basinger": "6448551",
    "Chris Foster": "6453223",
    "Anjana Patel": "6573660",
    "Betty Marlowe": "6632869",     # raw name 'RIDDLE, BETTY B'
    # Cyndi Mortimer 6481986 and Donald Long 6446578 are retired and not portal
    # users — they have no contract row to seed; the rollup handles their rows by
    # the name the parser already resolves from col 5.
}


def main():
    app = create_app()
    with app.app_context():
        updated, missing = [], []
        for name, wid in UHC_WRITING_IDS.items():
            u = User.query.filter(User.name == name).first()
            if not u:
                missing.append(name); continue
            c = AgentCarrierContract.query.filter_by(agent_id=u.id, carrier="UHC").first()
            if not c:
                missing.append(f"{name} (no UHC contract)"); continue
            if (c.id_value or "") != wid:
                c.id_value = wid
                c.id_type = "writing_number"
                updated.append(f"{name} -> {wid}")
        db.session.commit()
        print("Updated:")
        for u in updated:
            print("  ", u)
        if missing:
            print("Missing (no user/contract):")
            for m in missing:
                print("  ", m)
        if not updated:
            print("  (all already seeded)")


if __name__ == "__main__":
    main()
