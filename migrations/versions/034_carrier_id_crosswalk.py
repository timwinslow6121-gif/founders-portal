"""add carrier_id_crosswalk

Revision ID: 034
Revises: 033
"""
from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "carrier_id_crosswalk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("carrier", sa.String(length=32), nullable=False),
        sa.Column("carrier_key", sa.String(length=64), nullable=False),
        sa.Column("key_kind", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("mbi", sa.String(length=20)),
        sa.Column("confidence", sa.String(length=24), nullable=False, server_default="exact_id"),
        sa.Column("source_note", sa.String(length=256)),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "carrier", "carrier_key",
                            name="uq_crosswalk_agency_carrier_key"),
    )
    op.create_index("ix_carrier_id_crosswalk_agency_id", "carrier_id_crosswalk", ["agency_id"])
    op.create_index("ix_carrier_id_crosswalk_carrier", "carrier_id_crosswalk", ["carrier"])
    op.create_index("ix_carrier_id_crosswalk_customer_id", "carrier_id_crosswalk", ["customer_id"])

def downgrade():
    op.drop_table("carrier_id_crosswalk")
