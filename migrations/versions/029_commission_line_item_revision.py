"""commission_line_item_revisions table

Revision ID: 029
Revises: 028
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "commission_line_item_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("line_item_id", sa.Integer(),
                  sa.ForeignKey("commission_line_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("statement_id", sa.Integer(),
                  sa.ForeignKey("commission_statements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("before_json", sa.Text()),
        sa.Column("after_json", sa.Text()),
        sa.Column("sibling_source_ref", sa.String(length=160)),
        sa.Column("undone", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_cli_rev_agency", "commission_line_item_revisions", ["agency_id"])
    op.create_index("ix_cli_rev_line", "commission_line_item_revisions", ["line_item_id"])
    op.create_index("ix_cli_rev_statement", "commission_line_item_revisions", ["statement_id"])


def downgrade():
    op.drop_index("ix_cli_rev_statement", table_name="commission_line_item_revisions")
    op.drop_index("ix_cli_rev_line", table_name="commission_line_item_revisions")
    op.drop_index("ix_cli_rev_agency", table_name="commission_line_item_revisions")
    op.drop_table("commission_line_item_revisions")
