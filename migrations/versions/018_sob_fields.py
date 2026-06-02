"""Add sob_url, drug_tier4, drug_tier5 to plans table

Revision ID: 018
Revises: 017
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plans', sa.Column('sob_url',    sa.String(512), nullable=True))
    op.add_column('plans', sa.Column('drug_tier4', sa.String(32),  nullable=True))
    op.add_column('plans', sa.Column('drug_tier5', sa.String(32),  nullable=True))


def downgrade():
    op.drop_column('plans', 'drug_tier5')
    op.drop_column('plans', 'drug_tier4')
    op.drop_column('plans', 'sob_url')
