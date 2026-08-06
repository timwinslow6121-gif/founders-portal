"""provider_plans + Provider.group; drop bills_ppo_oon

Revision ID: 042
Revises: 041
"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("providers") as b:
        b.add_column(sa.Column("group", sa.String(length=256), nullable=True))
    op.create_table(
        "provider_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("bills_oon", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "plan_id", name="uq_provider_plan"),
    )
    op.create_index("ix_provider_plans_plan_id", "provider_plans", ["plan_id"])
    op.create_index("ix_provider_plans_provider_id", "provider_plans", ["provider_id"])
    with op.batch_alter_table("providers") as b:
        b.drop_column("bills_ppo_oon")


def downgrade():
    with op.batch_alter_table("providers") as b:
        b.add_column(sa.Column("bills_ppo_oon", sa.String(length=16), nullable=True))
    op.drop_index("ix_provider_plans_provider_id", table_name="provider_plans")
    op.drop_index("ix_provider_plans_plan_id", table_name="provider_plans")
    op.drop_table("provider_plans")
    with op.batch_alter_table("providers") as b:
        b.drop_column("group")
