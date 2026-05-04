"""add term_reason new_carrier new_plan_name to policies

Revision ID: 007
Revises: 006
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('policies', sa.Column('term_reason',   sa.String(32),  nullable=True))
    op.add_column('policies', sa.Column('new_carrier',   sa.String(64),  nullable=True))
    op.add_column('policies', sa.Column('new_plan_name', sa.String(256), nullable=True))


def downgrade():
    op.drop_column('policies', 'new_plan_name')
    op.drop_column('policies', 'new_carrier')
    op.drop_column('policies', 'term_reason')
