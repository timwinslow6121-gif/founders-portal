"""AgentRecapPeriod table (R2 agent commission recap)

Revision ID: 024
Revises: 023
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_recap_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("uhc_manual_amount", sa.Float(), nullable=True),
        sa.Column("uhc_manual_note", sa.String(length=256), nullable=True),
        sa.Column("prior_year_total", sa.Float(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agency_id", "agent_id", "period_label", name="uq_recap_agent_period"),
    )
    op.create_index("ix_agent_recap_periods_agency_id", "agent_recap_periods", ["agency_id"])
    op.create_index("ix_agent_recap_periods_agent_id", "agent_recap_periods", ["agent_id"])
    op.create_index("ix_agent_recap_periods_period_label", "agent_recap_periods", ["period_label"])


def downgrade():
    op.drop_table("agent_recap_periods")
