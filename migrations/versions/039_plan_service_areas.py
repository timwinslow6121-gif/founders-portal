"""plan_service_areas table

Revision ID: 039
Revises: 038
"""
from alembic import op
import sqlalchemy as sa

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_service_areas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("county", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "state", "county", name="uq_plan_service_area"),
    )
    op.create_index("ix_plan_service_areas_plan_id", "plan_service_areas", ["plan_id"])
    op.create_index("ix_plan_service_areas_agency_id", "plan_service_areas", ["agency_id"])


def downgrade():
    op.drop_index("ix_plan_service_areas_agency_id", table_name="plan_service_areas")
    op.drop_index("ix_plan_service_areas_plan_id", table_name="plan_service_areas")
    op.drop_table("plan_service_areas")
