"""investments: which instrument a buy belongs to (plan rules and manual assignments)

Revision ID: c9e1a7b3d5f2
Revises: b8d4f2a6c1e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9e1a7b3d5f2"
down_revision: Union[str, Sequence[str], None] = "b8d4f2a6c1e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "investment_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker", sa.String(), nullable=False, index=True),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
    )
    op.create_table(
        "investment_splits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_ref", sa.String(), nullable=False, index=True),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("investment_splits")
    op.drop_table("investment_rules")
