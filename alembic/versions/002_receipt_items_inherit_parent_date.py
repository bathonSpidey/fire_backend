"""receipt_items_inherit_parent_date

Updates all existing receipt items to use their parent transaction's date.
Going forward, AttachReceipt sets the date from the parent at creation time.

Revision ID: 002
Revises: 001
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Update all receipt items to inherit their parent's date
    op.execute("""
        UPDATE transactions
        SET date = (
            SELECT p.date
            FROM transactions p
            WHERE p.id = transactions.parent_transaction_id
        )
        WHERE parent_transaction_id IS NOT NULL
    """)


def downgrade() -> None:
    # Cannot recover original dates — no-op
    pass
