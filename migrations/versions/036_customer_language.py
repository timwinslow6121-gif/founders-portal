"""customer preferred language

Revision ID: 036
Revises: 035
"""
from alembic import op
import sqlalchemy as sa

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("language", sa.String(length=32)))


def downgrade():
    op.drop_column("customers", "language")
