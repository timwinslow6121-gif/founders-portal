"""add commission discrepancy override workflow columns

Revision ID: 006
Revises: 005
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('commission_statements') as batch_op:
        batch_op.add_column(sa.Column('override_note_admin', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('override_note_agent', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('override_requested_by_id', sa.Integer(),
                                      sa.ForeignKey('users.id'), nullable=True))
        batch_op.add_column(sa.Column('override_reviewed_by_id', sa.Integer(),
                                      sa.ForeignKey('users.id'), nullable=True))
        batch_op.add_column(sa.Column('override_requested_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('override_reviewed_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('commission_statements') as batch_op:
        batch_op.drop_column('override_reviewed_at')
        batch_op.drop_column('override_requested_at')
        batch_op.drop_column('override_reviewed_by_id')
        batch_op.drop_column('override_requested_by_id')
        batch_op.drop_column('override_note_agent')
        batch_op.drop_column('override_note_admin')
