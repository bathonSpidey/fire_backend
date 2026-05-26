"""
ORM models — the database representation.
These are NOT domain entities. Repositories translate between the two.
No domain code ever imports from this module.
"""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    documents: Mapped[list["DocumentORM"]] = relationship(back_populates="user")
    accounts: Mapped[list["AccountORM"]] = relationship(back_populates="user")
    transactions: Mapped[list["TransactionORM"]] = relationship(back_populates="user")
    insights: Mapped[list["InsightORM"]] = relationship(back_populates="user")


class AccountORM(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)
    institution: Mapped[str | None] = mapped_column(String(200))
    last_known_balance: Mapped[str | None] = mapped_column(Numeric(15, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    user: Mapped["UserORM"] = relationship(back_populates="accounts")
    transactions: Mapped[list["TransactionORM"]] = relationship(back_populates="account")


class DocumentORM(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    closing_balance: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    statement_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    user: Mapped["UserORM"] = relationship(back_populates="documents")
    transactions: Mapped[list["TransactionORM"]] = relationship(
        back_populates="document", foreign_keys="[TransactionORM.document_id]"
    )


class TransactionORM(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("accounts.id"))
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # ISO date: YYYY-MM-DD
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    amount: Mapped[str] = mapped_column(Numeric(15, 2), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    receipt_document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=True
    )
    transfer_account_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transfer_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_investment_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_transactions_user_year_month", "user_id", "date"),)

    user: Mapped["UserORM"] = relationship(back_populates="transactions")
    document: Mapped["DocumentORM"] = relationship(
        back_populates="transactions", foreign_keys="[TransactionORM.document_id]"
    )
    account: Mapped["AccountORM"] = relationship(back_populates="transactions")


class InsightORM(Base):
    __tablename__ = "insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    month: Mapped[int] = mapped_column(nullable=False)
    total_income: Mapped[str] = mapped_column(Numeric(15, 2), nullable=False)
    total_expenses: Mapped[str] = mapped_column(Numeric(15, 2), nullable=False)
    net_savings: Mapped[str] = mapped_column(Numeric(15, 2), nullable=False)
    savings_rate: Mapped[str] = mapped_column(Numeric(6, 2), nullable=False)
    spending_breakdown: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    llm_summary: Mapped[str] = mapped_column(Text, nullable=False)
    llm_tips: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fire_progress_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "year", "month", name="uq_insight_user_year_month"),
    )

    user: Mapped["UserORM"] = relationship(back_populates="insights")
