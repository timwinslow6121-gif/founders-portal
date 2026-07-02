"""add customers.preferred_name

Revision ID: 033
Revises: 032
"""
from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("preferred_name", sa.String(length=128), nullable=True))


def downgrade():
    op.drop_column("customers", "preferred_name")
