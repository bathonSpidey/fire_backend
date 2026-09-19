"""receipt ingestion fields + ingest_jobs queue table

Revision ID: a3c1e7f90b21
Revises: d19696d083f8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c1e7f90b21"
down_revision: Union[str, Sequence[str], None] = "d19696d083f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("owner", sa.String(), nullable=True))
        batch.add_column(sa.Column("source_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("file_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("receipt_number", sa.String(), nullable=True))
        batch.add_column(sa.Column("payment_method", sa.String(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(), nullable=False, server_default="ok"))
        batch.add_column(sa.Column("review_note", sa.String(), nullable=True))
        batch.create_index("ix_receipts_owner", ["owner"])
        batch.create_unique_constraint("uq_receipts_file_hash", ["file_hash"])
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(), nullable=False),
        sa.Column("inbox_path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=True),
        sa.Column("receipt_id", sa.Integer(), nullable=True),
        sa.Column("filed_path", sa.String(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ingest_jobs_owner", "ingest_jobs", ["owner"])
    op.create_index("ix_ingest_jobs_status", "ingest_jobs", ["status"])
    with op.batch_alter_table("inventory_items") as batch:
        batch.add_column(
            sa.Column("discount", sa.Float(), nullable=False, server_default="0.0")
        )


def downgrade() -> None:
    op.drop_table("ingest_jobs")
    with op.batch_alter_table("inventory_items") as batch:
        batch.drop_column("discount")
    with op.batch_alter_table("receipts") as batch:
        batch.drop_constraint("uq_receipts_file_hash", type_="unique")
        batch.drop_index("ix_receipts_owner")
        for col in ("review_note", "status", "payment_method", "receipt_number",
                    "file_hash", "source_path", "owner"):
            batch.drop_column(col)
