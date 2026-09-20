"""Dashboard numbers for one month: bank truth for income, receipts first for spending.

Two sources describe the household's money, and this combines them without counting anything
twice (the same rule as the Spending page, services/spending.py):

- Spending: receipt items by their own categories, plus bank payments that have no receipt. A
  bank booking linked to a receipt IS that receipt; a PayPal row explained by a bank booking is
  that booking. So a month is already meaningful from receipts alone, before any statement.
- Income and investments come from the bank statements (only the bank knows what arrived and
  what was moved into investments). Transfers between the household's own accounts are ignored.

The numbers are computed on request, never cached: receipts, statements, links and categories all
feed them, so a cache could only go stale.

A statement imported by the retired regex parser has no bank_transactions rows to read; it must
be uploaded again (it is replaced in place).
"""

import calendar
import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBReceipt, DBSpendCategory
from services.categories import category_map
from services.spending import Entry, collect_entries
from services.statement_store import MONTH_ABBR

INVESTMENTS_KEY = "investments"
UNCATEGORIZED_EXPENSE = "uncategorized"
UNCATEGORIZED_INCOME = "uncategorized_income"
DEFAULT_INCOME_BY_KIND = {"refund": "refunds_returns"}


def _meta(key: str, cats: dict[str, DBSpendCategory]) -> dict:
    if key == INVESTMENTS_KEY:
        return {"flow": "investment", "label": "Investments", "group": "Investments", "fixed": False}
    if key == UNCATEGORIZED_EXPENSE:
        return {"flow": "expense", "label": "Uncategorized", "group": "Other", "fixed": False}
    if key == UNCATEGORIZED_INCOME:
        return {"flow": "income", "label": "Uncategorized income", "group": "Income", "fixed": False}
    c = cats[key]
    return {"flow": c.flow, "label": c.label, "group": c.group_name, "fixed": bool(c.fixed)}


def _inflow_key(tx: DBBankTransaction, cats: dict[str, DBSpendCategory]) -> str:
    for key in (tx.category, DEFAULT_INCOME_BY_KIND.get(tx.kind)):
        if key in cats and cats[key].flow == "income":
            return key
    return "other_income" if "other_income" in cats else UNCATEGORIZED_INCOME


def metrics_from_sources(
    rows: list[DBBankTransaction],
    entries: list[Entry],
    month: str,
    year: int,
    cats: dict[str, DBSpendCategory],
    sources: dict | None = None,
) -> dict:
    """`rows`: the month's bank bookings (income and investments are read from these).
    `entries`: the month's spending (receipt items + bank payments without a receipt)."""
    gross_income = lifestyle_expenses = fixed_expenses = total_invested = 0.0
    totals: dict[str, float] = {}

    def add(key: str, amount: float) -> None:
        totals[key] = totals.get(key, 0.0) + amount

    for tx in rows:
        if tx.kind == "internal_transfer":
            continue
        if tx.kind == "investment":
            if tx.amount < 0:
                total_invested += -tx.amount
                add(INVESTMENTS_KEY, -tx.amount)
            continue  # proceeds of a sale are the same money coming back, not income
        if tx.amount > 0:
            gross_income += tx.amount
            add(_inflow_key(tx, cats), tx.amount)

    for entry in entries:
        lifestyle_expenses += entry.amount
        add(entry.key, entry.amount)
        if entry.key in cats and cats[entry.key].fixed:
            fixed_expenses += entry.amount

    net_savings = gross_income - lifestyle_expenses
    savings_rate = round(net_savings / gross_income * 100, 2) if gross_income > 0 else 0.0
    fixed_ratio = round(fixed_expenses / lifestyle_expenses * 100) if lifestyle_expenses > 0 else 0
    variable_ratio = 100 - fixed_ratio if lifestyle_expenses > 0 else 0

    categories = {}
    for key, total in totals.items():
        meta = _meta(key, cats)
        denominator = {"investment": total_invested, "income": gross_income}.get(
            meta["flow"], lifestyle_expenses
        )
        categories[key] = {
            "total": round(total, 2),
            "percentage_of_total": round(total / denominator * 100, 2) if denominator > 0 else 0.0,
            **meta,
        }

    return {
        "month": month,
        "year": year,
        "gross_income": round(gross_income, 2),
        "lifestyle_expenses": round(lifestyle_expenses, 2),
        "net_savings": round(net_savings, 2),
        "savings_rate_pct": savings_rate,
        "total_invested": round(total_invested, 2),
        "fixed_vs_variable_ratio": f"{fixed_ratio}% Fixed / {variable_ratio}% Variable",
        "categories": categories,
        "sources": sources or {"statements": [], "receipts": 0, "receipt_total": 0.0, "bank_only_total": 0.0},
    }


def calculate_metrics(db: Session, month: str, year: int) -> dict | None:
    """Numbers for a month ('Apr' + 2026), or None when there is nothing recorded for it."""
    month_number = MONTH_ABBR.index(month) + 1
    first = datetime.date(year, month_number, 1)
    last = datetime.date(year, month_number, calendar.monthrange(year, month_number)[1])

    statements = db.query(DBBankStatement).filter(
        DBBankStatement.month == month, DBBankStatement.year == year
    ).all()
    receipts = db.query(DBReceipt).filter(DBReceipt.purchase_date.between(first, last)).count()
    if not statements and receipts == 0:
        return None

    old = [f"{s.bank} {s.month} {s.year}" for s in statements if not s.bank_transactions]
    if old:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{', '.join(old)} was imported by the retired statement parser. "
                "Upload that statement again on the Upload page to include it."
            ),
        )

    cats = category_map(db, include_inactive=True)
    rows = (
        db.query(DBBankTransaction)
        .filter(
            DBBankTransaction.statement_id.in_([s.id for s in statements]),
            DBBankTransaction.mirror_of.is_(None),  # PayPal rows a bank booking already covers
        )
        .all()
        if statements
        else []
    )
    entries = collect_entries(db, first, last, cats)
    sources = {
        "statements": sorted({s.bank for s in statements}),
        "receipts": receipts,
        # how the spending adds up: what the receipts say + what was paid without a receipt
        "receipt_total": round(sum(e.amount for e in entries if e.source == "receipt"), 2),
        "bank_only_total": round(sum(e.amount for e in entries if e.source == "bank"), 2),
    }
    return metrics_from_sources(rows, entries, month, year, cats, sources)
