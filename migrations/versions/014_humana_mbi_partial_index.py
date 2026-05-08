"""humana mbi partial index + unresolvable_json column

Revision ID: 014
Revises: 013
Create Date: 2026-05-07

Replaces the simple unique index on customers.mbi with a partial unique
index that only enforces uniqueness for non-NULL values. This allows
Humana customers (who have no MBI in the carrier BOB) to coexist in the
table without constraint violations.

Also adds unresolvable_json TEXT column to import_batches, used by Plan
04-04 to quarantine BOB records with no resolvable MBI or Humana ID.

IMPORTANT: Run scripts/fix_humana_mbi.py --execute BEFORE applying this
migration. The partial index creation will succeed even if empty strings
exist, but subsequent Humana BOB imports would violate it for any
carrier=Humana rows that still have mbi=''.
"""
from alembic import op
import sqlalchemy as sa


revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing simple unique index on customers.mbi
    op.drop_index('ix_customers_mbi', table_name='customers')

    # Create partial unique index — only enforces uniqueness on non-NULL values.
    # NOTE: op.create_index() with postgresql_where MUST be called directly on op,
    # NOT inside batch_alter_table — Alembic constraint.
    op.create_index(
        'ix_customers_mbi',
        'customers',
        ['mbi'],
        unique=True,
        postgresql_where=sa.text('mbi IS NOT NULL'),
    )

    # Add unresolvable_json column to import_batches (used by Plan 04-04)
    op.add_column('import_batches', sa.Column('unresolvable_json', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('import_batches', 'unresolvable_json')

    op.drop_index('ix_customers_mbi', table_name='customers')

    with op.batch_alter_table('customers', schema=None) as batch_op:
        batch_op.create_index('ix_customers_mbi', ['mbi'], unique=True)
