"""Commission sync: stub/source on customers, flags + customer_id FK on policies, match_suggestions

Revision ID: 020
Revises: 019
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("customers", sa.Column("stub", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))
    op.add_column("customers", sa.Column("source", sa.String(32), nullable=True))

    op.add_column("policies", sa.Column("rapid_disenroll", sa.Boolean(), nullable=False,
                                        server_default=sa.false()))
    op.add_column("policies", sa.Column("commission_split_flag", sa.String(24), nullable=True))
    op.add_column("policies", sa.Column("customer_id", sa.Integer(),
                                        sa.ForeignKey("customers.id"), nullable=True))
    op.create_index("ix_policies_customer_id", "policies", ["customer_id"])

    # Backfill the new FK from the existing MBI join (the old implicit link).
    op.execute("""
        UPDATE policies p
        SET customer_id = c.id
        FROM customers c
        WHERE p.customer_id IS NULL
          AND p.mbi IS NOT NULL AND p.mbi <> ''
          AND c.mbi = p.mbi
          AND c.agency_id = p.agency_id
    """)
    op.execute("""
        UPDATE policies p
        SET customer_id = c.id
        FROM customers c
        WHERE p.customer_id IS NULL
          AND p.carrier = 'Humana'
          AND c.humana_id = p.member_id
          AND c.agency_id = p.agency_id
    """)

    op.create_table(
        "match_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=True),
        sa.Column("stub_customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("suggested_customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=True, server_default="pending"),
        sa.Column("source_member_fact_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_match_suggestions_agency_id", "match_suggestions", ["agency_id"])
    op.create_index("ix_match_suggestions_status", "match_suggestions", ["status"])
    op.create_index("ix_match_suggestions_stub_customer_id", "match_suggestions", ["stub_customer_id"])
    op.create_index("ix_match_suggestions_suggested_customer_id", "match_suggestions", ["suggested_customer_id"])

    # Per-row provenance key for payments. NON_CUSTOMER (HRA) rows have no member
    # identity and collapse on member_name_normalized, so dedup must key on
    # source_ref instead. Replace the name-based unique constraint accordingly.
    op.add_column("policy_payments", sa.Column("source_ref", sa.String(128), nullable=True))
    op.create_index("ix_policy_payments_source_ref", "policy_payments", ["source_ref"])
    op.drop_constraint("uq_payment_statement_member_action", "policy_payments", type_="unique")
    op.create_unique_constraint("uq_payment_statement_source_ref", "policy_payments",
                                ["statement_id", "source_ref"])


def downgrade():
    op.drop_constraint("uq_payment_statement_source_ref", "policy_payments", type_="unique")
    op.create_unique_constraint("uq_payment_statement_member_action", "policy_payments",
                                ["statement_id", "member_name_normalized", "commission_action"])
    op.drop_index("ix_policy_payments_source_ref", table_name="policy_payments")
    op.drop_column("policy_payments", "source_ref")

    op.drop_table("match_suggestions")
    op.drop_index("ix_policies_customer_id", table_name="policies")
    op.drop_column("policies", "customer_id")
    op.drop_column("policies", "commission_split_flag")
    op.drop_column("policies", "rapid_disenroll")
    op.drop_column("customers", "source")
    op.drop_column("customers", "stub")
