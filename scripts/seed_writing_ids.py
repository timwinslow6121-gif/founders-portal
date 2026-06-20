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
    # Humana: the BOB file's writing-agent column carries the agent's NPN (NOT the SAN).
    # Humana treats NPN and SAN interchangeably to identify an agent; the BOB sends NPN, so
    # that is the value the resolver must match. The SAN (used for Humana customer service)
    # is an operational reference, not an attribution key — kept off the contract row on
    # purpose (one row per agent). Confirmed by Tim 2026-06-20 from the live policy data.
    # This UPSERTS the agent's single Humana row in place (no duplicate rows).
    "Humana": {
        "Brian Freeman":   ("NPN", "19832009"),
        "Rebekah Long":    ("NPN", "20182775"),
        "Justin Basinger": ("NPN", "20446812"),
        "Chris Foster":    ("NPN", "20392239"),
        "Mike Lauzurique": ("NPN", "18052208"),
        "Anjana Patel":    ("NPN", "21041582"),
        "Timothy Winslow": ("NPN", "18708064"),
        "Betty Marlowe":   ("NPN", "6580706"),   # Betty Marlowe/Riddle NPN (her Humana book)
    },
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
                    # Humana: the row may currently hold the agent's SAN (used for Humana
                    # customer-service calls). The BOB/resolver needs the NPN, and the
                    # commission pipeline does NOT read the Humana id_value (only UHC's),
                    # so overwriting is safe — but preserve the old SAN in notes so it
                    # isn't lost as an operational reference.
                    if carrier == "Humana" and ct.id_value and ct.id_value != id_value:
                        san_note = f"Humana SAN (customer service): {ct.id_value}"
                        ct.notes = san_note if not ct.notes else f"{ct.notes} | {san_note}"
                        print(f"  KEPT SAN in notes for {name}: {ct.id_value}")
                    ct.id_value, ct.id_type = id_value, id_type
                    changed += 1
                    print(f"  SET {carrier} {name} -> {id_value}")
        db.session.commit()
        print(f"Done. {changed} contract id_values set/updated.")

if __name__ == "__main__":
    main()
