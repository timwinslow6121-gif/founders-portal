"""CommissionStatement.content_fingerprint for duplicate-upload detection

Revision ID: 021
Revises: 020
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("commission_statements",
                  sa.Column("content_fingerprint", sa.String(64), nullable=True))
    op.create_index("ix_commission_statements_content_fingerprint",
                    "commission_statements", ["content_fingerprint"])


def downgrade():
    op.drop_index("ix_commission_statements_content_fingerprint",
                  table_name="commission_statements")
    op.drop_column("commission_statements", "content_fingerprint")
