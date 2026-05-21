"""add_transfer_fields

Adds transfer_account_name and transfer_document_id to transactions.
Safe to run on existing data — both columns are nullable.

Revision ID: 003
Revises: 002
"""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(sa.Column("transfer_account_name", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("transfer_document_id", sa.String(36), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("transfer_document_id")
        batch_op.drop_column("transfer_account_name")
