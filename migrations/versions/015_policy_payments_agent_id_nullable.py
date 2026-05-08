"""policy_payments agent_id nullable for agency-level statements

Revision ID: 015
Revises: 014
Create Date: 2026-05-08

Aetna pays the agency directly across multiple LOA agents, so there is no
single portal user to attribute the statement to. Making agent_id nullable
allows agency-level commission statements (agent_id=NULL) to exist alongside
per-agent statements.
"""
from alembic import op


revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('policy_payments', 'agent_id', nullable=True)


def downgrade():
    op.alter_column('policy_payments', 'agent_id', nullable=False)
