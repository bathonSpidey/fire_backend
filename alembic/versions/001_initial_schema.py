"""initial_schema

Revision ID: 001
Revises:
Create Date: 2026-01-01
"""

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("institution", sa.String(200)),
        sa.Column("last_known_balance", sa.Numeric(15, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("document_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("uploaded_at", sa.DateTime, nullable=False),
        sa.Column("processed_at", sa.DateTime),
        sa.Column("error_message", sa.Text),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("accounts.id")),
        sa.Column("date", sa.String(10), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("transaction_type", sa.String(10), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("merchant", sa.String(200)),
        sa.Column("notes", sa.Text),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("parent_transaction_id", sa.String(36), sa.ForeignKey("transactions.id")),
        sa.Column("receipt_document_id", sa.String(36), sa.ForeignKey("documents.id")),
    )
    op.create_index("ix_transactions_user_year_month", "transactions", ["user_id", "date"])

    op.create_table(
        "insights",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("total_income", sa.Numeric(15, 2), nullable=False),
        sa.Column("total_expenses", sa.Numeric(15, 2), nullable=False),
        sa.Column("net_savings", sa.Numeric(15, 2), nullable=False),
        sa.Column("savings_rate", sa.Numeric(6, 2), nullable=False),
        sa.Column("spending_breakdown", sa.Text, nullable=False),
        sa.Column("llm_summary", sa.Text, nullable=False),
        sa.Column("llm_tips", sa.Text, nullable=False),
        sa.Column("generated_at", sa.DateTime, nullable=False),
        sa.Column("fire_progress_note", sa.Text),
        sa.UniqueConstraint("user_id", "year", "month", name="uq_insight_user_year_month"),
    )


def downgrade() -> None:
    op.drop_table("insights")
    op.drop_index("ix_transactions_user_year_month", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("documents")
    op.drop_table("accounts")
    op.drop_table("users")
