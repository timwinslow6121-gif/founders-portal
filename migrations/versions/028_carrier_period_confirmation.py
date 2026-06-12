"""Add carrier_period_confirmations (AJ confirms a carrier had $0 business for a period)

Lets the recap/matrix distinguish 'confirmed $0 — no business' from 'statement not
uploaded yet' for a carrier with no statement in a period.

Revision ID: 028
Revises: 027
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "carrier_period_confirmations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("confirmed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("note", sa.String(length=256)),
        sa.UniqueConstraint("agency_id", "carrier", "period_label",
                            name="uq_carrier_period_confirm"),
    )
    op.create_index("ix_carrier_period_confirmations_agency_id",
                    "carrier_period_confirmations", ["agency_id"])
    op.create_index("ix_carrier_period_confirmations_carrier",
                    "carrier_period_confirmations", ["carrier"])
    op.create_index("ix_carrier_period_confirmations_period_label",
                    "carrier_period_confirmations", ["period_label"])


def downgrade():
    op.drop_table("carrier_period_confirmations")
