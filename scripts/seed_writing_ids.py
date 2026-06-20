"""Seed AgentCarrierContract.id_value for ALL carriers (generalizes seed_uhc_writing_ids.py).

Each carrier uses its own ID system (Humana=SAN, UHC=AgentID, Devoted/Aetna-MAPD/
Healthspring=NPN, BCBS=pcode, Medico/Wellabe=writing #, GTL=agent code).
Idempotent. Run on VPS: PYTHONPATH=/var/www/founders-portal ./venv/bin/python3 scripts/seed_writing_ids.py
"""
from app import create_app
from app.extensions import db
from app.models import AgentCarrierContract, User

# carrier -> { "Agent Name": ("id_type", "id_value") }.  UHC is confirmed.
# Other carriers: Tim pastes confirmed IDs here before running (spec §4a).
WRITING_IDS = {
    "UHC": {
        "Timothy Winslow": ("agent_code", "6337213"),
        "Mike Lauzurique": ("agent_code", "6540381"),
        "Rebekah Long":    ("agent_code", "6435806"),
        "Brian Freeman":   ("agent_code", "6515098"),
        "Justin Basinger": ("agent_code", "6448551"),
        "Chris Foster":    ("agent_code", "6453223"),
        "Anjana Patel":    ("agent_code", "6573660"),
        "Betty Marlowe":   ("agent_code", "6632869"),
    },
    # "Humana": { "Brian Freeman": ("writing_number", "19832009"), ... },  # Tim fills
}

def main():
    app = create_app()
    with app.app_context():
        changed = 0
        for carrier, people in WRITING_IDS.items():
            for name, (id_type, id_value) in people.items():
                u = User.query.filter_by(name=name).first()
                if not u:
                    print(f"  SKIP (no user): {name}"); continue
                ct = AgentCarrierContract.query.filter_by(agent_id=u.id, carrier=carrier).first()
                if not ct:
                    ct = AgentCarrierContract(agent_id=u.id, carrier=carrier,
                                              agency_id=u.agency_id, is_active=True)
                    db.session.add(ct)
                if ct.id_value != id_value or ct.id_type != id_type:
                    ct.id_value, ct.id_type = id_value, id_type
                    changed += 1
                    print(f"  SET {carrier} {name} -> {id_value}")
        db.session.commit()
        print(f"Done. {changed} contract id_values set/updated.")

if __name__ == "__main__":
    main()
