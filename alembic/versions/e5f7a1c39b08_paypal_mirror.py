"""bank transactions can point at the bank booking they explain (PayPal detail rows)

Revision ID: e5f7a1c39b08
Revises: d8e3f1a7c290
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f7a1c39b08"
down_revision: Union[str, Sequence[str], None] = "d8e3f1a7c290"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bank_transactions", sa.Column("mirror_of", sa.Integer(), nullable=True))
    op.create_index("ix_bank_transactions_mirror_of", "bank_transactions", ["mirror_of"])


def downgrade() -> None:
    op.drop_index("ix_bank_transactions_mirror_of", table_name="bank_transactions")
    op.drop_column("bank_transactions", "mirror_of")
