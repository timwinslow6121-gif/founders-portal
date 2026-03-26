"""agency_id NOT NULL constraint after backfill

Revision ID: 003_agency_id_not_null
Revises: f003d6f5cb50
Create Date: 2026-03-25

IMPORTANT: Do NOT run this migration until scripts/seed_agency.py has been run
and all agency_id columns have been backfilled. Running this against rows with
NULL agency_id will fail with: "column contains null values".

VPS deployment sequence:
  1. flask db upgrade  (applies migrations 001 + 002 — creates agencies table, adds nullable columns)
  2. python scripts/seed_agency.py  (seeds "Founders Insurance Agency" row, backfills all agency_id)
  3. flask db upgrade  (applies migration 003 — adds NOT NULL constraint)
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '003_agency_id_not_null'
down_revision = 'f003d6f5cb50'
branch_labels = None
depends_on = None

TABLES = [
    'users', 'policies', 'customers', 'customer_notes',
    'customer_contacts', 'customer_aor_history',
    'agent_carrier_contracts', 'pharmacies', 'import_batches'
]


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column('agency_id', nullable=False)


def downgrade():
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column('agency_id', nullable=True)
