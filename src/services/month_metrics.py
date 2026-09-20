"""Monthly dashboard numbers computed from what Claude understood about each booking.

This is the "statement lens": the bank is the truth about money that actually moved. It reads
the explicit `kind` of every transaction:

- internal_transfer -> ignored (own money moving between accounts, paired or waiting for its pair)
- investment        -> counted as "invested" when money leaves; never income, never an expense
- everything else   -> income or expense by sign, split by the household's category list

(The live "receipt lens" with item-level detail is services/spending.py.)

A statement imported by the retired regex parser has no bank_transactions rows to read; it must
be uploaded again (it is replaced in place).
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBSpendCategory
from services.categories import category_map

INVESTMENTS_KEY = "investments"
UNCATEGORIZED_EXPENSE = "uncategorized"
UNCATEGORIZED_INCOME = "uncategorized_income"
DEFAULT_EXPENSE_BY_KIND = {"fee": "bank_fees", "cash": "cash"}
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


def _outflow_key(tx: DBBankTransaction, cats: dict[str, DBSpendCategory]) -> str:
    for key in (tx.category, DEFAULT_EXPENSE_BY_KIND.get(tx.kind)):
        if key in cats and cats[key].flow == "expense":
            return key
    return UNCATEGORIZED_EXPENSE


def _inflow_key(tx: DBBankTransaction, cats: dict[str, DBSpendCategory]) -> str:
    for key in (tx.category, DEFAULT_INCOME_BY_KIND.get(tx.kind)):
        if key in cats and cats[key].flow == "income":
            return key
    return "other_income" if "other_income" in cats else UNCATEGORIZED_INCOME


def metrics_from_transactions(
    rows: list[DBBankTransaction], month: str, year: int, cats: dict[str, DBSpendCategory]
) -> dict:
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
        elif tx.amount < 0:
            key = _outflow_key(tx, cats)
            lifestyle_expenses += -tx.amount
            add(key, -tx.amount)
            if key in cats and cats[key].fixed:
                fixed_expenses += -tx.amount

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
    }


def calculate_metrics(db: Session, statements: list[DBBankStatement], month: str, year: int) -> dict:
    """Month metrics for the given statement rows (all banks of that month)."""
    if statements and all(s.bank_transactions for s in statements):
        rows = (
            db.query(DBBankTransaction)
            .filter(DBBankTransaction.statement_id.in_([s.id for s in statements]))
            .all()
        )
        return metrics_from_transactions(rows, month, year, category_map(db, include_inactive=True))

    old = [f"{x.bank} {x.month} {x.year}" for x in statements if not x.bank_transactions]
    raise HTTPException(
        status_code=409,
        detail=(
            f"{', '.join(old)} was imported by the retired statement parser. "
            "Upload that statement again on the Upload page to include it."
        ),
    )
