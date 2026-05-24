"""add_is_investment_item

Adds is_investment_item flag to transactions.
Investment transactions come from attached bank statements (N26 etc.)
and should not appear in the main transaction list.

Revision ID: 005
Revises: 004
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_investment_item",
                sa.Boolean,
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.drop_column("is_investment_item")
