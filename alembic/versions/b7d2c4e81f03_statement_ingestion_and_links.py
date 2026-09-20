"""statement ingestion: bank_transactions, review_questions, links, job kind

Revision ID: b7d2c4e81f03
Revises: a3c1e7f90b21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2c4e81f03"
down_revision: Union[str, Sequence[str], None] = "a3c1e7f90b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("statements") as batch:
        batch.add_column(sa.Column("owner", sa.String(), nullable=True))
        batch.add_column(sa.Column("source_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("file_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("period_start", sa.Date(), nullable=True))
        batch.add_column(sa.Column("period_end", sa.Date(), nullable=True))
        batch.add_column(sa.Column("status", sa.String(), nullable=False, server_default="ok"))
        batch.add_column(sa.Column("review_note", sa.String(), nullable=True))
        batch.create_index("ix_statements_owner", ["owner"])
        batch.create_unique_constraint("uq_statements_file_hash", ["file_hash"])
    with op.batch_alter_table("receipts") as batch:
        batch.add_column(sa.Column("payment_reference", sa.String(), nullable=True))
    with op.batch_alter_table("ingest_jobs") as batch:
        batch.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="receipt"))

    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("statement_id", sa.Integer(), sa.ForeignKey("statements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("booking_date", sa.Date(), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("counterparty", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("payment_reference", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False, server_default="spend"),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("receipt_id", sa.Integer(), sa.ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("link_status", sa.String(), nullable=True),
        sa.Column("link_reason", sa.String(), nullable=True),
        sa.Column("transfer_group", sa.Integer(), nullable=True),
    )
    op.create_index("ix_bank_transactions_booking_date", "bank_transactions", ["booking_date"])
    op.create_index("ix_bank_transactions_transfer_group", "bank_transactions", ["transfer_group"])

    op.create_table(
        "review_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), sa.ForeignKey("bank_transactions.id", ondelete="CASCADE")),
        sa.Column("receipt_id", sa.Integer(), sa.ForeignKey("receipts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("other_transaction_id", sa.Integer(), sa.ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_review_questions_status", "review_questions", ["status"])


def downgrade() -> None:
    op.drop_table("review_questions")
    op.drop_table("bank_transactions")
    with op.batch_alter_table("ingest_jobs") as batch:
        batch.drop_column("kind")
    with op.batch_alter_table("receipts") as batch:
        batch.drop_column("payment_reference")
    with op.batch_alter_table("statements") as batch:
        batch.drop_constraint("uq_statements_file_hash", type_="unique")
        batch.drop_index("ix_statements_owner")
        for col in ("review_note", "period_end", "period_start",
                    "file_hash", "source_path", "owner", "status"):
            batch.drop_column(col)
