"""
scripts/backfill_customer_provenance.py

One-time, idempotent backfill seeding per-field provenance for existing customers.

- manually_edited=True  -> every populated tracked field seeded as agent_entered
  (protect everything a human touched; a later carrier mismatch flags a conflict).
- manually_edited=False -> every populated tracked field seeded as carrier_import.
- source recorded from customer.source where present, else 'bob' (carrier-tier);
  manually_edited uses source='agent_edit'.
- Idempotent: a field that already has provenance is skipped.

Run on VPS:  ./venv/bin/python3 scripts/backfill_customer_provenance.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import customer_provenance as cp


def _seed_source(customer):
    return (getattr(customer, "source", None) or "bob")


def seed_customer(customer):
    """Seed provenance for one customer's populated tracked fields (idempotent).
    Returns the number of fields seeded."""
    data = cp._load(customer)
    meta = data.setdefault("_meta", {})
    trust = "agent_entered" if customer.manually_edited else "carrier_import"
    src = "agent_edit" if customer.manually_edited else _seed_source(customer)
    seeded = 0
    for field in cp.PROVENANCE_FIELDS:
        if field in meta:
            continue
        raw = getattr(customer, field, None)
        if cp._is_blank(raw):
            continue
        meta[field] = {
            "value": cp._to_scalar(raw),
            "source": src,
            "trust": trust,
            "updated_at": cp._now(),
            "updated_by": None,
            "history": [{"at": cp._now(), "by": None, "from": None,
                         "to": cp._to_scalar(raw), "note": "provenance backfill"}],
        }
        seeded += 1
    cp._save(customer, data)
    return seeded


def main():
    from app import create_app
    from app.extensions import db
    from app.models import Customer

    app = create_app()
    with app.app_context():
        total_customers = 0
        total_fields = 0
        for c in Customer.query.all():
            n = seed_customer(c)
            if n:
                total_customers += 1
                total_fields += n
        db.session.commit()
        print(f"Backfilled provenance: {total_fields} fields across "
              f"{total_customers} customers.")


if __name__ == "__main__":
    main()
