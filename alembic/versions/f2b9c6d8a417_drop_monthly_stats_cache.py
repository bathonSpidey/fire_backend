"""drop the monthly_stats cache: dashboard numbers are computed live now

Revision ID: f2b9c6d8a417
Revises: e5f7a1c39b08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2b9c6d8a417"
down_revision: Union[str, Sequence[str], None] = "e5f7a1c39b08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("monthly_stats")


def downgrade() -> None:
    op.create_table(
        "monthly_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("month", sa.String(length=3), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("gross_income", sa.Float(), nullable=False),
        sa.Column("lifestyle_expenses", sa.Float(), nullable=False),
        sa.Column("net_savings", sa.Float(), nullable=False),
        sa.Column("total_invested", sa.Float(), nullable=False),
        sa.Column("savings_rate_pct", sa.Float(), nullable=False),
        sa.Column("fixed_vs_variable_ratio", sa.String(length=50), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
    )
