"""CommissionLineItem table (R1 commission ledger completeness)

Revision ID: 023
Revises: 022
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_line_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("statement_id", sa.Integer(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.Column("period_label", sa.String(length=32), nullable=True),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("member_name", sa.String(length=256), nullable=True),
        sa.Column("mbi", sa.String(length=20), nullable=True),
        sa.Column("carrier_member_id", sa.String(length=128), nullable=True),
        sa.Column("raw_amount", sa.Float(), nullable=False),
        sa.Column("split_rate", sa.Float(), nullable=True),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("payment_type", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["statement_id"], ["commission_statements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("statement_id", "source_ref", name="uq_lineitem_statement_source_ref"),
    )
    op.create_index("ix_commission_line_items_agency_id", "commission_line_items", ["agency_id"])
    op.create_index("ix_commission_line_items_statement_id", "commission_line_items", ["statement_id"])
    op.create_index("ix_commission_line_items_carrier", "commission_line_items", ["carrier"])
    op.create_index("ix_commission_line_items_period_label", "commission_line_items", ["period_label"])
    op.create_index("ix_commission_line_items_source_ref", "commission_line_items", ["source_ref"])
    op.create_index("ix_commission_line_items_agent_id", "commission_line_items", ["agent_id"])
    op.create_index("ix_commission_line_items_customer_id", "commission_line_items", ["customer_id"])
    op.create_index("ix_commission_line_items_mbi", "commission_line_items", ["mbi"])
    op.create_index("ix_commission_line_items_classification", "commission_line_items", ["classification"])


def downgrade():
    op.drop_table("commission_line_items")
