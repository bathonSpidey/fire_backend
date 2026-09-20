"""editable spend categories; receipt items and bank transactions use them

Revision ID: c4a9d6e2b5f1
Revises: b7d2c4e81f03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from services.category_seed import LEGACY_BANK_TO_KEY, LEGACY_ITEM_TO_KEY, SEED

revision: str = "c4a9d6e2b5f1"
down_revision: Union[str, Sequence[str], None] = "b7d2c4e81f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    table = op.create_table(
        "spend_categories",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("group_name", sa.String(), nullable=False),
        sa.Column("flow", sa.String(), nullable=False, server_default="expense"),
        sa.Column("fixed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.bulk_insert(
        table,
        [
            {"key": key, "label": label, "group_name": group, "flow": flow, "fixed": fixed,
             "description": description, "sort_order": order * 10, "active": True}
            for order, (key, label, group, flow, fixed, description, _legacy) in enumerate(SEED)
        ],
    )

    op.add_column("inventory_items", sa.Column("spend_category", sa.String(), nullable=True))
    op.create_index("ix_inventory_items_spend_category", "inventory_items", ["spend_category"])

    bind = op.get_bind()
    for legacy, key in LEGACY_ITEM_TO_KEY.items():
        bind.execute(
            sa.text("UPDATE inventory_items SET spend_category = :key WHERE category = :legacy"),
            {"key": key, "legacy": legacy},
        )
    for legacy, key in LEGACY_BANK_TO_KEY.items():
        bind.execute(
            sa.text("UPDATE bank_transactions SET category = :key WHERE category = :legacy"),
            {"key": key, "legacy": legacy},
        )
    # Anything still carrying an old ALL-CAPS key is ambiguous: leave it empty for a Claude re-check.
    bind.execute(sa.text("UPDATE bank_transactions SET category = NULL WHERE category = UPPER(category)"))
    bind.execute(sa.text("UPDATE bank_transactions SET category = 'cash' WHERE category IS NULL AND kind = 'cash'"))
    bind.execute(sa.text("UPDATE bank_transactions SET category = 'bank_fees' WHERE category IS NULL AND kind = 'fee'"))


def downgrade() -> None:
    op.drop_index("ix_inventory_items_spend_category", table_name="inventory_items")
    op.drop_column("inventory_items", "spend_category")
    op.drop_table("spend_categories")
