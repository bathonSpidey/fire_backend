"""investment plans (savings plans with a schedule) replace the unused investment_rules table

Revision ID: d2f5b8a1c4e6
Revises: c9e1a7b3d5f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2f5b8a1c4e6"
down_revision: Union[str, Sequence[str], None] = "c9e1a7b3d5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("investment_rules")  # created one step earlier, never filled
    op.create_table(
        "investment_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker", sa.String(), nullable=False, index=True),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("frequency", sa.String(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("investment_plans")
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
