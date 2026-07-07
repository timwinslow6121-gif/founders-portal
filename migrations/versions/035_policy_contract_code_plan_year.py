"""policy contract_code + plan_year, plan needs_review

Revision ID: 035
Revises: 034
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("policies", sa.Column("contract_code", sa.String(length=32)))
    op.add_column("policies", sa.Column("plan_year", sa.Integer()))
    op.create_index("ix_policies_contract_code", "policies", ["contract_code"])
    op.create_index("ix_policies_plan_year", "policies", ["plan_year"])
    op.add_column("plans", sa.Column("needs_review", sa.Boolean(),
                                     nullable=False, server_default=sa.false()))

def downgrade():
    op.drop_column("plans", "needs_review")
    op.drop_index("ix_policies_plan_year", table_name="policies")
    op.drop_index("ix_policies_contract_code", table_name="policies")
    op.drop_column("policies", "plan_year")
    op.drop_column("policies", "contract_code")
