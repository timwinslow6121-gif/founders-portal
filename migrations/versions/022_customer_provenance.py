"""Customer field-provenance: field_provenance + has_unresolved_conflicts

Revision ID: 022
Revises: 021
Create Date: 2026-06-05
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("field_provenance", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("has_unresolved_conflicts", sa.Boolean(),
                                         nullable=False, server_default=sa.false()))
    op.create_index("ix_customers_has_unresolved_conflicts", "customers",
                    ["has_unresolved_conflicts"])


def downgrade():
    op.drop_index("ix_customers_has_unresolved_conflicts", table_name="customers")
    op.drop_column("customers", "has_unresolved_conflicts")
    op.drop_column("customers", "field_provenance")
