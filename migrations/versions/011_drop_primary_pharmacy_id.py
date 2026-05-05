"""drop primary_pharmacy_id from users (replaced by pharmacy_agents many-to-many)

Revision ID: 011
Revises: 010
Create Date: 2026-05-05
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('users', 'primary_pharmacy_id')


def downgrade():
    op.add_column('users', sa.Column('primary_pharmacy_id', sa.Integer(),
                  sa.ForeignKey('pharmacies.id'), nullable=True))
