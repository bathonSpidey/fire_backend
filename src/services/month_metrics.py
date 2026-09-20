"""Monthly dashboard numbers computed from what Claude understood about each booking.

The old engine guessed with regexes on the description text and could not know that a booking
is one half of a transfer between the household's own accounts. This one reads the explicit
`kind` of every transaction:

- internal_transfer -> ignored (own money moving between accounts, paired or waiting for its pair)
- investment        -> counted as "invested" when money leaves; never income, never an expense
- everything else   -> income or expense by sign

A statement imported by the retired regex parser has no bank_transactions rows to read; it must
be uploaded again (it is replaced in place, keeping nothing but the data it came from).
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction

# The frontend (categoryClassifier.ts) treats exactly these keys as income.
INCOME_CATEGORIES = {"SALARY", "RETURNS", "OTHER_INCOME"}
INVESTMENT_KEY = "INVESTMENT_ORDER"
FIXED_KEY = "FIXED_COSTS"


def _expense_category(tx: DBBankTransaction) -> str:
    if tx.kind == "fee":
        return FIXED_KEY
    if tx.kind == "cash":
        return "CASH"
    if tx.category and tx.category not in INCOME_CATEGORIES:
        return tx.category
    return "OTHER_EXPENSE"


def _income_category(tx: DBBankTransaction) -> str:
    if tx.category in INCOME_CATEGORIES:
        return tx.category
    return "RETURNS" if tx.kind == "refund" else "OTHER_INCOME"


def metrics_from_transactions(rows: list[DBBankTransaction], month: str, year: int) -> dict:
    gross_income = lifestyle_expenses = fixed_expenses = total_invested = 0.0
    totals: dict[str, float] = {}

    def add(category: str, amount: float) -> None:
        totals[category] = totals.get(category, 0.0) + amount

    for tx in rows:
        if tx.kind == "internal_transfer":
            continue
        if tx.kind == "investment":
            if tx.amount < 0:
                total_invested += -tx.amount
                add(INVESTMENT_KEY, -tx.amount)
            continue  # proceeds of a sale are the same money coming back, not income
        if tx.amount > 0:
            gross_income += tx.amount
            add(_income_category(tx), tx.amount)
        elif tx.amount < 0:
            category = _expense_category(tx)
            lifestyle_expenses += -tx.amount
            add(category, -tx.amount)
            if category == FIXED_KEY:
                fixed_expenses += -tx.amount

    net_savings = gross_income - lifestyle_expenses
    savings_rate = round(net_savings / gross_income * 100, 2) if gross_income > 0 else 0.0
    fixed_ratio = round(fixed_expenses / lifestyle_expenses * 100) if lifestyle_expenses > 0 else 0
    variable_ratio = 100 - fixed_ratio if lifestyle_expenses > 0 else 0

    categories = {}
    for category, total in totals.items():
        if category == INVESTMENT_KEY:
            denominator = total_invested
        elif category in INCOME_CATEGORIES:
            denominator = gross_income
        else:
            denominator = lifestyle_expenses
        categories[category] = {
            "total": round(total, 2),
            "percentage_of_total": round(total / denominator * 100, 2) if denominator > 0 else 0.0,
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
        return metrics_from_transactions(rows, month, year)

    old = [f"{x.bank} {x.month} {x.year}" for x in statements if not x.bank_transactions]
    raise HTTPException(
        status_code=409,
        detail=(
            f"{', '.join(old)} was imported by the retired statement parser. "
            "Upload that statement again on the Upload page to include it."
        ),
    )
