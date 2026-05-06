"""policy_payments table

Revision ID: 013
Revises: 012
Create Date: 2026-05-06

Per-member payment ledger. One row per member per commission statement period.
Replaces JSON line_items blob as queryable source of truth for reconciliation.
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'policy_payments',
        sa.Column('id',                     sa.Integer,     primary_key=True),
        sa.Column('agency_id',              sa.Integer,     sa.ForeignKey('agencies.id'),              nullable=False),
        sa.Column('agent_id',               sa.Integer,     sa.ForeignKey('users.id'),                 nullable=False),
        sa.Column('statement_id',           sa.Integer,     sa.ForeignKey('commission_statements.id',
                                                            ondelete='CASCADE'),                       nullable=False),
        sa.Column('carrier',                sa.String(64),  nullable=False),
        sa.Column('period_label',           sa.String(32),  nullable=False),
        sa.Column('statement_date',         sa.Date,        nullable=True),
        sa.Column('member_name',            sa.String(256), nullable=False),
        sa.Column('member_name_normalized', sa.String(256), nullable=True),
        sa.Column('mbi',                    sa.String(20),  nullable=True),
        sa.Column('carrier_member_id',      sa.String(128), nullable=True),
        sa.Column('policy_id',              sa.Integer,     sa.ForeignKey('policies.id'), nullable=True),
        sa.Column('match_confidence',       sa.String(32),  nullable=True, server_default='unmatched'),
        sa.Column('commission_action',      sa.String(32),  nullable=False),
        sa.Column('paid_amount',            sa.Float,       nullable=False),
        sa.Column('is_chargeback',          sa.Boolean,     nullable=False, server_default='false'),
        sa.Column('effective_date',         sa.Date,        nullable=True),
        sa.Column('term_date',              sa.Date,        nullable=True),
        sa.Column('term_reason',            sa.String(128), nullable=True),
        sa.Column('period_month',           sa.String(16),  nullable=True),
        sa.Column('plan_name',              sa.String(256), nullable=True),
        sa.Column('created_at',             sa.DateTime,    server_default=sa.func.now()),
    )
    op.create_index('ix_policy_payments_agency_id',              'policy_payments', ['agency_id'])
    op.create_index('ix_policy_payments_agent_id',               'policy_payments', ['agent_id'])
    op.create_index('ix_policy_payments_statement_id',           'policy_payments', ['statement_id'])
    op.create_index('ix_policy_payments_carrier',                'policy_payments', ['carrier'])
    op.create_index('ix_policy_payments_period_label',           'policy_payments', ['period_label'])
    op.create_index('ix_policy_payments_mbi',                    'policy_payments', ['mbi'])
    op.create_index('ix_policy_payments_member_name_normalized', 'policy_payments', ['member_name_normalized'])
    op.create_index('ix_policy_payments_commission_action',      'policy_payments', ['commission_action'])
    op.create_unique_constraint(
        'uq_payment_statement_member_action',
        'policy_payments',
        ['statement_id', 'member_name_normalized', 'commission_action']
    )


def downgrade():
    op.drop_table('policy_payments')
