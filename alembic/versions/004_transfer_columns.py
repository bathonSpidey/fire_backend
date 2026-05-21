"""transfer_columns

Adds transfer_account_name and transfer_document_id to transactions table.
Sets default bank name for existing transfer transactions.

Revision ID: 004
Revises: 003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    insp = inspect(conn)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _column_exists("transactions", "transfer_account_name"):
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.add_column(sa.Column("transfer_account_name", sa.String(200), nullable=True))

    if not _column_exists("transactions", "transfer_document_id"):
        with op.batch_alter_table("transactions") as batch_op:
            batch_op.add_column(sa.Column("transfer_document_id", sa.String(36), nullable=True))

    # Default bank name for existing transfer transactions from Sparkasse
    op.execute("""
        UPDATE transactions
        SET transfer_account_name = 'Sparkasse'
        WHERE category = 'transfer'
          AND (transfer_account_name IS NULL OR transfer_account_name = '')
    """)


def downgrade() -> None:
    pass
