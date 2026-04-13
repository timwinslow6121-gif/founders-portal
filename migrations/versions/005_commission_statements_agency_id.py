"""add agency_id to commission_statements

Revision ID: 005_commission_statements_agency_id
Revises: 004_phase3_comms_schema
Create Date: 2026-04-13

commission_statements was missing agency_id — added manually on VPS 2026-04-13.
This migration is a no-op if the column already exists (applied via psql ALTER TABLE).
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004_phase3_comms_schema'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('commission_statements') as batch_op:
        batch_op.add_column(sa.Column('agency_id', sa.Integer(), sa.ForeignKey('agencies.id'), nullable=True))
        batch_op.create_index('ix_commission_statements_agency_id', ['agency_id'])


def downgrade():
    with op.batch_alter_table('commission_statements') as batch_op:
        batch_op.drop_index('ix_commission_statements_agency_id')
        batch_op.drop_column('agency_id')
