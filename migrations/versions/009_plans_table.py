"""add plans table

Revision ID: 009
Revises: 008
Create Date: 2026-05-04
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'plans',
        sa.Column('id',               sa.Integer(),     primary_key=True),
        sa.Column('agency_id',        sa.Integer(),     sa.ForeignKey('agencies.id'), nullable=False, index=True),
        sa.Column('carrier',          sa.String(64),    nullable=False),
        sa.Column('plan_name',        sa.String(256),   nullable=False),
        sa.Column('year',             sa.Integer(),     nullable=False),
        sa.Column('plan_type',        sa.String(32),    nullable=False),
        sa.Column('plan_subtype',     sa.String(32)),
        sa.Column('is_dsnp',          sa.Boolean(),     default=False),
        sa.Column('is_csnp',          sa.Boolean(),     default=False),
        sa.Column('is_5star',         sa.Boolean(),     default=False),
        sa.Column('star_rating',      sa.Float()),
        sa.Column('cms_plan_id',      sa.String(32)),
        sa.Column('plan_letter',      sa.String(4)),
        sa.Column('external_id',      sa.String(128)),
        sa.Column('status',           sa.String(32),    nullable=False, server_default='current'),
        sa.Column('is_commissionable',sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('auto_transitioned',sa.Boolean(),     default=False),
        sa.Column('successor_plan_id',sa.Integer(),     sa.ForeignKey('plans.id'), nullable=True),
        sa.Column('service_area',     sa.String(256)),
        sa.Column('monthly_premium',  sa.Float()),
        sa.Column('annual_oopm',      sa.Float()),
        sa.Column('pcp_copay',        sa.String(32)),
        sa.Column('specialist_copay', sa.String(32)),
        sa.Column('er_copay',         sa.String(32)),
        sa.Column('drug_tier1',       sa.String(32)),
        sa.Column('drug_tier2',       sa.String(32)),
        sa.Column('drug_tier3',       sa.String(32)),
        sa.Column('details_json',     sa.Text()),
        sa.Column('comm_type',        sa.String(32),    server_default='pmpm'),
        sa.Column('comm_initial',     sa.Float()),
        sa.Column('comm_renewal',     sa.Float()),
        sa.Column('comm_trueup',      sa.Float()),
        sa.Column('hra_bonus',        sa.Float()),
        sa.Column('comm_notes',       sa.Text()),
        sa.Column('plan_name_aliases',sa.Text()),
        sa.Column('created_by_id',    sa.Integer(),     sa.ForeignKey('users.id')),
        sa.Column('created_at',       sa.DateTime(),    server_default=sa.func.now()),
        sa.Column('updated_at',       sa.DateTime(),    server_default=sa.func.now()),
        sa.UniqueConstraint('agency_id', 'carrier', 'cms_plan_id', 'year', name='uq_plan_carrier_year'),
    )
    op.create_index('ix_plans_carrier', 'plans', ['carrier'])
    op.create_index('ix_plans_year',    'plans', ['year'])
    op.create_index('ix_plans_status',  'plans', ['status'])
    op.create_index('ix_plans_cms_plan_id', 'plans', ['cms_plan_id'])


def downgrade():
    op.drop_table('plans')
