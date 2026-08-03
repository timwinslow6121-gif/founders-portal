"""commission_line_items.writing_agent_raw — writing-agent provenance

The retired-agent rollup (app/commission/rollup.py) rewrites Cyndi Mortimer and
Don Long to Brian Freeman BEFORE agent-matching, so `agent_id` records who gets
PAID but nothing records whose BOOK the business came from. The value is already
computed during import and was discarded; this column keeps it.

Nullable by design: rows imported before this landed stay NULL (an honest
"unknown"), and a backfill from the raw carrier files can fill them in later
matched on source_ref. Provenance only — never used in the split math.

Revision ID: 040
Revises: 039
"""
from alembic import op
import sqlalchemy as sa

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commission_line_items",
                  sa.Column("writing_agent_raw", sa.String(length=128), nullable=True))
    op.create_index("ix_commission_line_items_writing_agent_raw",
                    "commission_line_items", ["writing_agent_raw"])


def downgrade():
    op.drop_index("ix_commission_line_items_writing_agent_raw",
                  table_name="commission_line_items")
    op.drop_column("commission_line_items", "writing_agent_raw")
