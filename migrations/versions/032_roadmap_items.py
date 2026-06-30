"""roadmap_items — roadmap/changelog entries + agent bug submissions

Revision ID: 032
Revises: 031
"""
from alembic import op
import sqlalchemy as sa

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "roadmap_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False, server_default="bug_fix"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("issue_text", sa.Text(), nullable=True),
        sa.Column("fix_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("priority", sa.String(length=8), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("shipped_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_roadmap_items_agency_id", "roadmap_items", ["agency_id"])
    op.create_index("ix_roadmap_items_status", "roadmap_items", ["status"])
    op.create_index("ix_roadmap_items_submitted_by_id", "roadmap_items", ["submitted_by_id"])


def downgrade():
    op.drop_index("ix_roadmap_items_submitted_by_id", table_name="roadmap_items")
    op.drop_index("ix_roadmap_items_status", table_name="roadmap_items")
    op.drop_index("ix_roadmap_items_agency_id", table_name="roadmap_items")
    op.drop_table("roadmap_items")
