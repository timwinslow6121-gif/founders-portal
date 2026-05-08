"""add customer_saved_views table

Revision ID: 016
Revises: 015
Create Date: 2026-05-08

Named filter+column presets for the customer list. Personal (is_shared=False)
or shared agency-wide (is_shared=True). Scoped per agency for multi-tenant safety.
"""
import sqlalchemy as sa
from alembic import op


revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'customer_saved_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('agency_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('state_json', sa.Text(), nullable=False),
        sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['agency_id'], ['agencies.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_customer_saved_views_agency_id', 'customer_saved_views', ['agency_id'])


def downgrade():
    op.drop_index('ix_customer_saved_views_agency_id', table_name='customer_saved_views')
    op.drop_table('customer_saved_views')
