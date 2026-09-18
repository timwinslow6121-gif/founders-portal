"""users.npn — National Producer Number, per person not per carrier

Revision ID: 044
Revises: 043
"""
from alembic import op
import sqlalchemy as sa

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("npn", sa.String(length=16), nullable=True))
    op.create_index("ix_users_npn", "users", ["npn"])


def downgrade():
    op.drop_index("ix_users_npn", table_name="users")
    with op.batch_alter_table("users") as b:
        b.drop_column("npn")
