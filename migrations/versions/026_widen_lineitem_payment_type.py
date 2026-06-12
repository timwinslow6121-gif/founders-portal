"""Widen commission_line_items.payment_type 32 -> 256

UHC quarantine (needs_manual_review) rows store the full Commission Action
description (e.g. "New, DVH Manual Payment, DVH 1000 Plan, ... written by ...")
so AJ can triage them in the quarantine tab. That string exceeds the old
VARCHAR(32) and broke real UHC uploads with StringDataRightTruncation.

Revision ID: 026
Revises: 025
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("commission_line_items") as batch:
        batch.alter_column(
            "payment_type",
            existing_type=sa.String(length=32),
            type_=sa.String(length=256),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("commission_line_items") as batch:
        batch.alter_column(
            "payment_type",
            existing_type=sa.String(length=256),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
