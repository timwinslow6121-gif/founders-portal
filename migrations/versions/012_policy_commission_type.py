"""policy_commission_type

Revision ID: 012
Revises: 011
Create Date: 2026-05-06

Add commission_type to policies table.
Values: NULL=unknown, 'initial'=first-ever MA enrollment, 'renewal'=all other MA enrollments.
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('policies',
        sa.Column('commission_type', sa.String(16), nullable=True)
    )


def downgrade():
    op.drop_column('policies', 'commission_type')
