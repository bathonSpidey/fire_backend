import datetime

from sqlalchemy import JSON, Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class DBBankStatement(Base):
    __tablename__ = "statements"

    id = Column(Integer, primary_key=True, index=True)
    bank = Column(String, nullable=False)
    month = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    starting_balance = Column(Float, nullable=False)
    closing_balance = Column(Float, nullable=False)

    # Store the list of BankTransaction objects as a JSON array natively
    transactions = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)


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

class DBInventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    unit_cost = Column(Float, nullable=False)
    category = Column(String, nullable=False)  # Maps from ItemCategory Enum string
    storage_condition = Column(String, nullable=False) # Maps from StorageCondition Enum string
    date_purchased = Column(Date, nullable=False)
    date_expiry = Column(Date, nullable=True) # purchase_date + estimated_shelf_life_days
    status = Column(String, default="Available") # Available, Consumed, Wasted
