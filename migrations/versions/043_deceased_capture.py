"""deceased_date + term_reason_raw

Revision ID: 043
Revises: 042
"""
from alembic import op
import sqlalchemy as sa

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customers") as b:
        b.add_column(sa.Column("deceased_date", sa.Date(), nullable=True))
    op.create_index("ix_customers_deceased_date", "customers", ["deceased_date"])
    with op.batch_alter_table("policies") as b:
        b.add_column(sa.Column("term_reason_raw", sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table("policies") as b:
        b.drop_column("term_reason_raw")
    op.drop_index("ix_customers_deceased_date", table_name="customers")
    with op.batch_alter_table("customers") as b:
        b.drop_column("deceased_date")
