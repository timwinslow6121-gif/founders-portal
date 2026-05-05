"""add primary_pharmacy_id to users

Revision ID: 010
Revises: 009
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('primary_pharmacy_id', sa.Integer(),
                  sa.ForeignKey('pharmacies.id'), nullable=True))


def downgrade():
    op.drop_column('users', 'primary_pharmacy_id')
