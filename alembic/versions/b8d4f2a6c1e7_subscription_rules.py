"""what the household decided about detected subscriptions (hide, set the frequency)

Revision ID: b8d4f2a6c1e7
Revises: a7c3e9d1f2b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d4f2a6c1e7"
down_revision: Union[str, Sequence[str], None] = "a7c3e9d1f2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription_rules",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("frequency", sa.String(), nullable=True),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("subscription_rules")
