"""providers + provider_carriers tables

Revision ID: 041
Revises: 040
"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agency_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("provider_type", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("county", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("bills_ppo_oon", sa.String(length=16), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_providers_agency_id", "providers", ["agency_id"])
    op.create_index("ix_providers_county", "providers", ["county"])
    op.create_table(
        "provider_carriers",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("carrier", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("provider_id", "carrier"),
    )


def downgrade():
    op.drop_table("provider_carriers")
    op.drop_index("ix_providers_county", table_name="providers")
    op.drop_index("ix_providers_agency_id", table_name="providers")
    op.drop_table("providers")
