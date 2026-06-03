"""Plan provenance columns + User.role (RBAC foundation)

Revision ID: 019
Revises: 018
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plans", sa.Column("cms_synced_at", sa.DateTime(), nullable=True))
    op.add_column("plans", sa.Column("has_unresolved_conflicts", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))
    op.create_index("ix_plans_has_unresolved_conflicts", "plans",
                    ["has_unresolved_conflicts"])
    op.add_column("users", sa.Column("role", sa.String(16), nullable=False,
                                     server_default="agent"))
    # Backfill: existing admins -> 'admin'. Everyone else stays 'agent' (safe
    # read-only default). senior_agent promotions are an EXPLICIT, VERIFIED
    # post-migration step on the VPS — NOT guessed here, because a wrong match
    # would grant shared-data edit rights to the wrong person.
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")


def downgrade():
    op.drop_column("users", "role")
    op.drop_index("ix_plans_has_unresolved_conflicts", table_name="plans")
    op.drop_column("plans", "has_unresolved_conflicts")
    op.drop_column("plans", "cms_synced_at")
