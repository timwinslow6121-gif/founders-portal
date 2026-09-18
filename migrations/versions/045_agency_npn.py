"""agencies.npn — the agency's own National Producer Number

Revision ID: 045
Revises: 044
"""
from alembic import op
import sqlalchemy as sa

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agencies") as b:
        b.add_column(sa.Column("npn", sa.String(length=16), nullable=True))


def downgrade():
    with op.batch_alter_table("agencies") as b:
        b.drop_column("npn")
