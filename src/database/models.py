import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class DBBankStatement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)
    bank = Column(String, nullable=False)
    month = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    starting_balance = Column(Float, nullable=False)
    closing_balance = Column(Float, nullable=False)

    # DERIVED copy of bank_transactions in the legacy shape, kept in sync by
    # services.statement_store.sync_statement_json so the existing dashboards keep working.
    transactions = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Provenance and review state (set by the Claude ingestion pipeline)
    owner = Column(String, nullable=True, index=True)
    source_path = Column(String, nullable=True)
    file_hash = Column(String, nullable=True, unique=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    status = Column(String, default="ok", nullable=False)  # ok | needs_review
    review_note = Column(String, nullable=True)
    bank_transactions = relationship(
        "DBBankTransaction", back_populates="statement", cascade="all, delete-orphan"
    )


class DBMonthlyStat(Base):
    __tablename__ = "monthly_stats"

    id = Column(Integer, primary_key=True, index=True)
    month = Column(String(3), nullable=False, index=True)
    year = Column(Integer, nullable=False, index=True)
    gross_income = Column(Float, nullable=False)
    lifestyle_expenses = Column(Float, nullable=False)
    net_savings = Column(Float, nullable=False)
    total_invested = Column(Float, nullable=False)
    savings_rate_pct = Column(Float, nullable=False)
    fixed_vs_variable_ratio = Column(String(50), nullable=False)

    # Stores the raw dictionary breakdown: dict[str, CategorySummary]
    categories = Column(JSON, nullable=False)


class DBReceipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    store_name = Column(String, nullable=False)
    total_amount = Column(Float, nullable=False)
    total_discount = Column(Float, default=0.0)
    purchase_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    bank_statement_linked = Column(Boolean, default=False, nullable=False)

    # Provenance and review state (set by the Claude ingestion pipeline)
    owner = Column(String, nullable=True, index=True)  # household member who uploaded it
    source_path = Column(String, nullable=True)  # where the original file is filed
    file_hash = Column(String, nullable=True, unique=True)  # sha256 of the uploaded file
    receipt_number = Column(String, nullable=True)  # "Bon" number printed on the receipt
    payment_reference = Column(String, nullable=True)  # e.g. Bluecode transaction number
    payment_method = Column(String, nullable=True)  # e.g. "Kaufland Pay", "Card", "Cash"
    status = Column(String, default="ok", nullable=False)  # ok | needs_review
    review_note = Column(String, nullable=True)  # why extraction wasn't clean

    items = relationship("DBInventoryItem", back_populates="receipt", cascade="all, delete-orphan")

class DBInventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    unit_cost = Column(Float, nullable=False)  # price of ONE unit, before discount
    discount = Column(Float, default=0.0, nullable=False)  # line discount (positive number)
    category = Column(String, nullable=False)  # Maps from ItemCategory Enum string
    storage_condition = Column(String, nullable=False)  # Maps from StorageCondition Enum string
    date_purchased = Column(Date, nullable=False)
    date_expiry = Column(Date, nullable=True)  # purchase_date + estimated_shelf_life_days
    # Spending category (key of spend_categories); `category` above is the coarse pantry grouping
    spend_category = Column(String, nullable=True, index=True)
    status = Column(String, default="Available")  # Available, Consumed, Wasted
    receipt = relationship("DBReceipt", back_populates="items")


class DBIngestJob(Base):
    """One uploaded file waiting for / going through Claude extraction.

    Persisted so the queue survives restarts (the laptop is switched off every night).
    """

    __tablename__ = "ingest_jobs"

    id = Column(Integer, primary_key=True, index=True)
    owner = Column(String, nullable=False, index=True)
    original_name = Column(String, nullable=False)
    inbox_path = Column(String, nullable=False)
    # queued | processing | saved | needs_review | duplicate | failed
    kind = Column(String, nullable=False, default="receipt")  # receipt | statement
    status = Column(String, nullable=False, default="queued", index=True)
    message = Column(String, nullable=True)
    receipt_id = Column(Integer, nullable=True)
    filed_path = Column(String, nullable=True)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class DBBankTransaction(Base):
    """One booking on a bank/PayPal statement. Source of truth for linking."""

    __tablename__ = "bank_transactions"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("statements.id", ondelete="CASCADE"), nullable=False)
    booking_date = Column(Date, nullable=False, index=True)
    purchase_date = Column(Date, nullable=True)  # real purchase day if the text reveals it
    amount = Column(Float, nullable=False)  # negative = money out
    counterparty = Column(String, nullable=False)  # clean name, e.g. "Kaufland"
    description = Column(String, nullable=False)  # raw text, whitespace-normalised
    channel = Column(String, nullable=True)  # SEPA | Card | Bluecode | PayPal | ...
    payment_reference = Column(String, nullable=True)  # ids usable to match other documents
    # spend | income | internal_transfer | investment | fee | cash | refund | other
    kind = Column(String, nullable=False, default="spend")
    category = Column(String, nullable=True)

    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="SET NULL"), nullable=True)
    link_status = Column(String, nullable=True)  # auto | confirmed
    link_reason = Column(String, nullable=True)
    transfer_group = Column(Integer, nullable=True, index=True)  # pairs both sides of a transfer

    statement = relationship("DBBankStatement", back_populates="bank_transactions")


class DBReviewQuestion(Base):
    """A yes/no question for the household when Claude is not sure about a link."""

    __tablename__ = "review_questions"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, nullable=False)  # receipt_match | transfer_match
    transaction_id = Column(Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"))
    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=True)
    other_transaction_id = Column(
        Integer, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=True
    )
    question = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open", index=True)  # open | yes | no
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    answered_at = Column(DateTime, nullable=True)



class DBSpendCategory(Base):
    """The household's editable category list, shared by receipts, statements and the dashboards."""

    __tablename__ = "spend_categories"

    key = Column(String, primary_key=True)  # stable id, e.g. "ev_charging"
    label = Column(String, nullable=False)
    group_name = Column(String, nullable=False)
    flow = Column(String, nullable=False, default="expense")  # expense | income
    fixed = Column(Boolean, nullable=False, default=False)  # counts as a fixed cost
    description = Column(String, nullable=True)  # what Claude reads to decide
    sort_order = Column(Integer, nullable=False, default=100)
    active = Column(Boolean, nullable=False, default=True)
