"""AEP pipeline tables

Revision ID: 046
Revises: 045
"""
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pipeline_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("track", sa.String(16), nullable=False, server_default="renewal"),
        sa.Column("stage", sa.String(16), nullable=False, server_default="contact"),
        sa.Column("outcome", sa.String(16)),
        sa.Column("stage_since", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_try_at", sa.DateTime()),
        sa.Column("intake_status", sa.String(24)),
        sa.Column("waiting_what", sa.String(256)),
        sa.Column("waiting_due", sa.Date()),
        sa.Column("sep_end", sa.Date()),
        sa.Column("sep_reason", sa.String(128)),
        sa.Column("shp_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shp_confirmed_at", sa.DateTime()),
        sa.Column("tier_override", sa.Integer()),
        sa.Column("tier_override_note", sa.Text()),
        sa.Column("tier_override_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("tier_override_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("customer_id", name="uq_pipeline_state_customer"),
    )
    op.create_index("ix_pipeline_state_agency_id", "pipeline_state", ["agency_id"])
    op.create_index("ix_pipeline_state_customer_id", "pipeline_state", ["customer_id"])
    op.create_index("ix_pipeline_state_stage_since", "pipeline_state", ["stage", "stage_since"])
    op.create_index("ix_pipeline_state_waiting_due", "pipeline_state", ["waiting_due"])
    op.create_index("ix_pipeline_state_sep_end", "pipeline_state", ["sep_end"])

    op.create_table(
        "touch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("channel", sa.String(24), nullable=False),
        sa.Column("direction", sa.String(8)),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(128)),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("outcome_recorded_at", sa.DateTime()),
        sa.UniqueConstraint("external_id", name="uq_touch_external_id"),
    )
    op.create_index("ix_touch_agency_id", "touch", ["agency_id"])
    op.create_index("ix_touch_customer_id", "touch", ["customer_id"])
    op.create_index("ix_touch_occurred_at", "touch", ["occurred_at"])
    op.create_index("ix_touch_customer_occurred", "touch", ["customer_id", "occurred_at"])

    op.create_table(
        "appointment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(24)),
        sa.Column("source", sa.String(24)),
        sa.Column("external_id", sa.String(128)),
        sa.Column("outcome_recorded_at", sa.DateTime()),
    )
    op.create_index("ix_appointment_agency_id", "appointment", ["agency_id"])
    op.create_index("ix_appointment_customer_id", "appointment", ["customer_id"])
    op.create_index("ix_appointment_agent_starts", "appointment", ["agent_id", "starts_at"])

    op.create_table(
        "application",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id")),
        sa.Column("submitted_at", sa.DateTime()),
        sa.Column("via", sa.String(32)),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("problem", sa.String(128)),
        sa.Column("problem_at", sa.DateTime()),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("ix_application_agency_id", "application", ["agency_id"])
    op.create_index("ix_application_customer_id", "application", ["customer_id"])

    op.create_table(
        "scope_form",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("method", sa.String(24)),
        sa.Column("products", sa.Text()),
        sa.Column("captured_by", sa.Integer(), sa.ForeignKey("users.id")),
    )
    op.create_index("ix_scope_form_agency_id", "scope_form", ["agency_id"])
    op.create_index("ix_scope_form_customer_id", "scope_form", ["customer_id"])

    op.create_table(
        "authorized_contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("relationship", sa.String(64)),
        sa.Column("phone", sa.String(32)),
        sa.Column("may_discuss_coverage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("linked_customer_id", sa.Integer(), sa.ForeignKey("customers.id")),
    )
    op.create_index("ix_authorized_contact_agency_id", "authorized_contact", ["agency_id"])
    op.create_index("ix_authorized_contact_customer_id", "authorized_contact", ["customer_id"])
    op.create_index("ix_authorized_contact_phone", "authorized_contact", ["phone"])

    op.create_table(
        "plan_rating",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("rating", sa.Integer()),
        sa.Column("note", sa.Text()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "plan_id", name="uq_plan_rating"),
    )
    op.create_index("ix_plan_rating_agency_id", "plan_rating", ["agency_id"])
    op.create_index("ix_plan_rating_plan_id", "plan_rating", ["plan_id"])

    op.create_table(
        "sar_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("county", sa.String(128), nullable=False),
        sa.Column("state", sa.String(8), server_default="NC"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", "plan_id", "county", name="uq_sar_rule"),
    )
    op.create_index("ix_sar_rule_agency_id", "sar_rule", ["agency_id"])
    op.create_index("ix_sar_rule_plan_id", "sar_rule", ["plan_id"])

    op.create_table(
        "pipeline_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agency_id", sa.Integer(), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("season_start", sa.Date()),
        sa.Column("season_end", sa.Date()),
        sa.Column("shp_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("shp_start", sa.Date()),
        sa.Column("shp_end", sa.Date()),
        sa.Column("sep_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("stall_contact_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("stall_deciding_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("stall_submitted_days", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("rules_status", sa.String(8), nullable=False, server_default="draft"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("agency_id", name="uq_pipeline_config_agency"),
    )


def downgrade():
    for t in ("pipeline_config", "sar_rule", "plan_rating", "authorized_contact",
              "scope_form", "application", "appointment", "touch", "pipeline_state"):
        op.drop_table(t)
