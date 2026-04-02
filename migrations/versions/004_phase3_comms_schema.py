"""phase3 comms schema

Revision ID: 004_phase3_comms_schema
Revises: 003_agency_id_not_null
Create Date: 2026-04-02

Adds all Phase 3 communications hub schema changes:
  - customer_notes: quo_call_id, twilio_msg_sid, retell_call_id, resolved
  - customers: sms_consent_at
  - users: quo_user_id
  - new table: unmatched_calls
  - new table: sms_templates
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004_phase3_comms_schema'
down_revision = '003_agency_id_not_null'
branch_labels = None
depends_on = None


def upgrade():
    # --- customer_notes: Phase 3 integration columns ---
    with op.batch_alter_table('customer_notes') as batch_op:
        batch_op.add_column(sa.Column('quo_call_id', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('twilio_msg_sid', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('retell_call_id', sa.String(128), nullable=True))
        batch_op.add_column(sa.Column('resolved', sa.Boolean(), nullable=False,
                                      server_default=sa.text('false')))

    # --- customers: SMS consent timestamp ---
    with op.batch_alter_table('customers') as batch_op:
        batch_op.add_column(sa.Column('sms_consent_at', sa.DateTime(), nullable=True))

    # --- users: Quo userId mapping ---
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('quo_user_id', sa.String(64), nullable=True))

    # --- new table: unmatched_calls ---
    op.create_table(
        'unmatched_calls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agency_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('provider', sa.String(32), nullable=True, server_default='quo'),
        sa.Column('call_sid', sa.String(128), nullable=True),
        sa.Column('from_number', sa.String(32), nullable=True),
        sa.Column('to_number', sa.String(32), nullable=True),
        sa.Column('direction', sa.String(16), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.Column('resolved', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(), nullable=True),
        sa.Column('resolved_note_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['users.id']),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['resolved_note_id'], ['customer_notes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_unmatched_calls_agency_id', 'unmatched_calls', ['agency_id'])
    op.create_index('ix_unmatched_calls_agent_id', 'unmatched_calls', ['agent_id'])

    # --- new table: sms_templates ---
    op.create_table(
        'sms_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agency_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('status', sa.String(32), nullable=True, server_default='pending'),
        sa.Column('created_by_id', sa.Integer(), nullable=False),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sms_templates_agency_id', 'sms_templates', ['agency_id'])


def downgrade():
    # --- drop sms_templates ---
    op.drop_index('ix_sms_templates_agency_id', table_name='sms_templates')
    op.drop_table('sms_templates')

    # --- drop unmatched_calls ---
    op.drop_index('ix_unmatched_calls_agent_id', table_name='unmatched_calls')
    op.drop_index('ix_unmatched_calls_agency_id', table_name='unmatched_calls')
    op.drop_table('unmatched_calls')

    # --- users: remove quo_user_id ---
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('quo_user_id')

    # --- customers: remove sms_consent_at ---
    with op.batch_alter_table('customers') as batch_op:
        batch_op.drop_column('sms_consent_at')

    # --- customer_notes: remove Phase 3 columns ---
    with op.batch_alter_table('customer_notes') as batch_op:
        batch_op.drop_column('resolved')
        batch_op.drop_column('retell_call_id')
        batch_op.drop_column('twilio_msg_sid')
        batch_op.drop_column('quo_call_id')
