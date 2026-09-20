"""inventory becomes a real stock: quantity left, location, opened, rating, waste

Revision ID: a7c3e9d1f2b6
Revises: f2b9c6d8a417
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e9d1f2b6"
down_revision: Union[str, Sequence[str], None] = "f2b9c6d8a417"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("inventory_items", sa.Column("quantity_left", sa.Float(), nullable=True))
    op.add_column("inventory_items", sa.Column("wasted_quantity", sa.Float(), nullable=False, server_default="0"))
    op.add_column("inventory_items", sa.Column("wasted_on", sa.Date(), nullable=True))
    op.add_column("inventory_items", sa.Column("waste_reason", sa.String(), nullable=True))
    op.add_column("inventory_items", sa.Column("opened_on", sa.Date(), nullable=True))
    op.add_column("inventory_items", sa.Column("days_once_opened", sa.Integer(), nullable=True))
    op.add_column("inventory_items", sa.Column("finished_on", sa.Date(), nullable=True))
    op.add_column("inventory_items", sa.Column("location", sa.String(), nullable=True))
    op.add_column("inventory_items", sa.Column("rating", sa.Integer(), nullable=True))
    op.add_column("inventory_items", sa.Column("would_rebuy", sa.Boolean(), nullable=True))

    # Existing items: what was available is still all there; what was thrown away was all of it.
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE inventory_items SET quantity_left = CASE WHEN status = 'Available' THEN quantity ELSE 0 END"))
    bind.execute(sa.text(
        "UPDATE inventory_items SET wasted_quantity = quantity, wasted_on = date_purchased, "
        "finished_on = date_purchased, waste_reason = CASE WHEN status = 'Spoiled' THEN 'spoiled' ELSE 'other' END "
        "WHERE status IN ('Spoiled', 'Discarded')"
    ))
    bind.execute(sa.text("UPDATE inventory_items SET finished_on = date_purchased WHERE status = 'Consumed'"))


def downgrade() -> None:
    for column in ("would_rebuy", "rating", "location", "finished_on", "days_once_opened",
                   "opened_on", "waste_reason", "wasted_on", "wasted_quantity", "quantity_left"):
        op.drop_column("inventory_items", column)
