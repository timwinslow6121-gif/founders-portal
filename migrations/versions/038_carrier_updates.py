"""carrier updates (medicare updates hub, phase 1)

Revision ID: 038
Revises: 037
"""
from alembic import op
import sqlalchemy as sa

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "carrier_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("update_type", sa.String(length=24), nullable=False, server_default="general"),
        sa.Column("carrier", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_until", sa.Date(), nullable=True),
        sa.Column("posted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_carrier_updates_agency_id", "carrier_updates", ["agency_id"])


def downgrade():
    op.drop_index("ix_carrier_updates_agency_id", table_name="carrier_updates")
    op.drop_table("carrier_updates")
