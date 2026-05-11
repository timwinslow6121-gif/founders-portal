"""Add plans.friendly_name and policies.plan_id FK

Revision ID: 017
Revises: 016
Create Date: 2026-05-11

plans.friendly_name — agent-facing short name (e.g. "NC-0015", "UHC Plan 3")
policies.plan_id    — FK → plans.id, resolved at BOB upload via plan_name_aliases
"""
import sqlalchemy as sa
from alembic import op

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plans', sa.Column('friendly_name', sa.String(128), nullable=True))
    op.add_column('policies', sa.Column('plan_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_policies_plan_id', 'policies', 'plans', ['plan_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_policies_plan_id', 'policies', ['plan_id'])


def downgrade():
    op.drop_index('ix_policies_plan_id', table_name='policies')
    op.drop_constraint('fk_policies_plan_id', 'policies', type_='foreignkey')
    op.drop_column('policies', 'plan_id')
    op.drop_column('plans', 'friendly_name')
