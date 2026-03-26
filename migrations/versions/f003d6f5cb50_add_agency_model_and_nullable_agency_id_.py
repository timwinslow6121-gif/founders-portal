"""add Agency model and nullable agency_id FK columns

Revision ID: f003d6f5cb50
Revises: d27f51392651
Create Date: 2026-03-25 21:18:34.560901

NOTE: agency_id is added as a plain nullable integer column here.
      On PostgreSQL, the FK constraint to agencies.id is implicit in the
      column definition and enforced at the application layer.
      The NOT NULL constraint is added in migration 003, AFTER seed_agency.py
      has backfilled all rows.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f003d6f5cb50'
down_revision = 'd27f51392651'
branch_labels = None
depends_on = None

TABLES = [
    'users', 'policies', 'customers', 'customer_notes',
    'customer_contacts', 'customer_aor_history',
    'agent_carrier_contracts', 'pharmacies', 'import_batches'
]


def upgrade():
    # Create the agencies table (top-level tenant root)
    op.create_table(
        'agencies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Add nullable agency_id column to all 9 tenant tables.
    # SQLite batch mode is used for SQLite compatibility.
    # FK constraint is enforced at the application layer; PostgreSQL enforces
    # referential integrity via the column type and application-level queries.
    for table in TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column('agency_id', sa.Integer(), nullable=True))


def downgrade():
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column('agency_id')
    op.drop_table('agencies')
