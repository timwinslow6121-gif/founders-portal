"""S2: add security/forensic fields to audit_logs

Revision ID: 025
Revises: 024
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("ip_address", sa.String(length=45), nullable=True))
        batch.add_column(sa.Column("user_agent", sa.String(length=256), nullable=True))
        batch.add_column(sa.Column("agency_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("category", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("severity", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("record_count", sa.Integer(), nullable=True))
    op.create_index("ix_audit_logs_agency_id", "audit_logs", ["agency_id"])
    op.create_index("ix_audit_logs_category", "audit_logs", ["category"])


def downgrade():
    op.drop_index("ix_audit_logs_category", table_name="audit_logs")
    op.drop_index("ix_audit_logs_agency_id", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("record_count")
        batch.drop_column("severity")
        batch.drop_column("category")
        batch.drop_column("agency_id")
        batch.drop_column("user_agent")
        batch.drop_column("ip_address")
