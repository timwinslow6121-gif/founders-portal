"""add pharmacy_agents join table

Revision ID: 008
Revises: 007
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pharmacy_agents',
        sa.Column('pharmacy_id', sa.Integer(), sa.ForeignKey('pharmacies.id'), primary_key=True),
        sa.Column('user_id',     sa.Integer(), sa.ForeignKey('users.id'),      primary_key=True),
    )


def downgrade():
    op.drop_table('pharmacy_agents')
