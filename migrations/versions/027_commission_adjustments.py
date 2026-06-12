"""Add commission_adjustments (manual per-agent/carrier/period reconciliation line)

AJ can add a signed adjustment + note to one agent's carrier block for a period
to reconcile a prior over/underpayment; it flows into the recap total. Visible to
the agent (transparent).

Revision ID: 027
Revises: 026
"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("note", sa.String(length=256), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_commission_adjustments_agency_id", "commission_adjustments", ["agency_id"])
    op.create_index("ix_commission_adjustments_agent_id", "commission_adjustments", ["agent_id"])
    op.create_index("ix_commission_adjustments_carrier", "commission_adjustments", ["carrier"])
    op.create_index("ix_commission_adjustments_period_label", "commission_adjustments", ["period_label"])


def downgrade():
    op.drop_table("commission_adjustments")
