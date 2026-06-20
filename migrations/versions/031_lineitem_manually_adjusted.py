"""commission_line_items.manually_adjusted (AJ hand-corrected split survives re-upload)

Revision ID: 031
Revises: 030
"""
from alembic import op
import sqlalchemy as sa

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commission_line_items",
                  sa.Column("manually_adjusted", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("commission_line_items", "manually_adjusted")
