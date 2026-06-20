"""commission_statements balance columns (A3 balance gate)

Revision ID: 030
Revises: 029
"""
from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commission_statements", sa.Column("balanced", sa.Boolean(), nullable=True))
    op.add_column("commission_statements", sa.Column("ledger_total", sa.Float(), nullable=True))
    op.add_column("commission_statements", sa.Column("money_rows_total", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("commission_statements", "money_rows_total")
    op.drop_column("commission_statements", "ledger_total")
    op.drop_column("commission_statements", "balanced")
