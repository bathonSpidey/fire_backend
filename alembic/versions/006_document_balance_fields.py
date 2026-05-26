"""document_balance_fields

Adds closing_balance, statement_date, account_name to documents table.

Revision ID: 006
Revises: 005
"""

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("closing_balance", sa.Numeric(12, 2), nullable=True))
        batch_op.add_column(sa.Column("statement_date", sa.String(10), nullable=True))
        batch_op.add_column(sa.Column("account_name", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("account_name")
        batch_op.drop_column("statement_date")
        batch_op.drop_column("closing_balance")
