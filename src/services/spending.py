"""Live spending for one month: receipts first, the bank fills the gaps.

Per the household's flow:
- Receipts are itemised and dated at the purchase, so a month can be tracked from receipts alone.
- A bank booking linked to a receipt IS that receipt (its items are counted, the booking is not).
- A bank booking with no receipt counts on its own, by its own category. The bank is the truth
  about money that really moved; receipts may be missed or forgotten.
- Gaps are reported instead of hidden: receipts that never appeared on a statement, and bank
  payments at stores that normally give receipts but have none uploaded.

Transfers and investments are not spending. Income is on the statement lens (month_metrics).
"""

import calendar
import datetime
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBReceipt, DBSpendCategory
from services.categories import UNCATEGORIZED_KEY, category_map
from services.statement_store import MONTH_ABBR

SPEND_KINDS = ("spend", "fee", "cash", "other")
DEFAULT_BY_KIND = {"fee": "bank_fees", "cash": "cash"}
TOP_STORES = 10


@dataclass
class Entry:
    key: str
    amount: float
    source: str  # "receipt" | "bank"
    owner: str | None
    store: str


def _bounds(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    return datetime.date(year, month, 1), datetime.date(year, month, calendar.monthrange(year, month)[1])


def _resolve(key: str | None, cats: dict[str, DBSpendCategory]) -> str:
    return key if key in cats and cats[key].flow == "expense" else UNCATEGORIZED_KEY


def collect_entries(
    db: Session, first: datetime.date, last: datetime.date, cats: dict[str, DBSpendCategory]
) -> list[Entry]:
    entries: list[Entry] = []
    for receipt in db.query(DBReceipt).filter(DBReceipt.purchase_date.between(first, last)):
        for item in receipt.items:
            amount = round((item.quantity or 1) * item.unit_cost - (item.discount or 0.0), 2)
            entries.append(Entry(_resolve(item.spend_category, cats), amount, "receipt",
                                 receipt.owner, receipt.store_name))

    on_purchase_day = and_(
        DBBankTransaction.purchase_date.isnot(None), DBBankTransaction.purchase_date.between(first, last)
    )
    on_booking_day = and_(
        DBBankTransaction.purchase_date.is_(None), DBBankTransaction.booking_date.between(first, last)
    )
    bank_rows = (
        db.query(DBBankTransaction, DBBankStatement.owner)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(
            DBBankTransaction.kind.in_(SPEND_KINDS),
            DBBankTransaction.amount < 0,
            DBBankTransaction.receipt_id.is_(None),  # linked ones are already counted as receipts
            or_(on_purchase_day, on_booking_day),
        )
    )
    for tx, owner in bank_rows:
        key = _resolve(tx.category or DEFAULT_BY_KIND.get(tx.kind), cats)
        entries.append(Entry(key, round(-tx.amount, 2), "bank", owner, tx.counterparty))
    return entries


def _sum_by(entries: list[Entry], attr: str) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for e in entries:
        totals[getattr(e, attr) or "Unknown"] += e.amount
    return {k: round(v, 2) for k, v in totals.items()}


def _discrepancies(db: Session, year: int, month: int, first: datetime.date, last: datetime.date) -> dict:
    label = MONTH_ABBR[month - 1]
    statements = db.query(DBBankStatement).filter(
        DBBankStatement.month == label, DBBankStatement.year == year
    ).all()
    has_statement = any(s.bank_transactions for s in statements)

    receipts = db.query(DBReceipt).filter(DBReceipt.purchase_date.between(first, last)).all()
    unmatched = [
        {"receipt_id": r.id, "store": r.store_name, "date": r.purchase_date.isoformat(),
         "total": r.total_amount, "owner": r.owner}
        for r in receipts if not r.bank_statement_linked
    ]

    # Stores that have ever given us a receipt: a bank payment there without one is suspicious.
    known_stores = {name.lower() for (name,) in db.query(DBReceipt.store_name).distinct()}
    missing = []
    if has_statement:
        rows = (
            db.query(DBBankTransaction)
            .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
            .filter(
                DBBankStatement.month == label, DBBankStatement.year == year,
                DBBankTransaction.kind == "spend", DBBankTransaction.amount < 0,
                DBBankTransaction.receipt_id.is_(None),
            )
        )
        for tx in rows:
            name = tx.counterparty.lower()
            if any(store in name or name in store for store in known_stores):
                missing.append({"transaction_id": tx.id, "date": tx.booking_date.isoformat(),
                                "amount": round(-tx.amount, 2), "counterparty": tx.counterparty})
    return {
        "has_statement": has_statement,
        # Before the statement exists, unmatched receipts are simply "not booked yet", not a problem.
        "awaiting_statement": not has_statement and bool(receipts),
        "unmatched_receipts": unmatched if has_statement else [],
        "missing_receipts": missing,
    }


def month_spending(db: Session, year: int, month: int) -> dict:
    cats = category_map(db, include_inactive=True)
    first, last = _bounds(year, month)
    entries = collect_entries(db, first, last, cats)
    prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
    pfirst, plast = _bounds(prev_year, prev_month)
    previous = _sum_by(collect_entries(db, pfirst, plast, cats), "key")

    total = round(sum(e.amount for e in entries), 2)
    receipt_by_cat = _sum_by([e for e in entries if e.source == "receipt"], "key")
    bank_by_cat = _sum_by([e for e in entries if e.source == "bank"], "key")

    def meta(key: str) -> dict:
        if key == UNCATEGORIZED_KEY:
            return {"label": "Uncategorized", "group": "Other", "fixed": False}
        c = cats[key]
        return {"label": c.label, "group": c.group_name, "fixed": bool(c.fixed)}

    categories = []
    for key in set(receipt_by_cat) | set(bank_by_cat):
        amount = round(receipt_by_cat.get(key, 0.0) + bank_by_cat.get(key, 0.0), 2)
        categories.append({
            "key": key, **meta(key), "amount": amount,
            "receipt_amount": receipt_by_cat.get(key, 0.0), "bank_amount": bank_by_cat.get(key, 0.0),
            "share_pct": round(amount / total * 100, 1) if total > 0 else 0.0,
            "previous_amount": previous.get(key, 0.0),
        })
    categories.sort(key=lambda c: -c["amount"])

    groups: dict[str, float] = defaultdict(float)
    for c in categories:
        groups[c["group"]] += c["amount"]

    receipts = db.query(DBReceipt).filter(DBReceipt.purchase_date.between(first, last)).all()
    store_totals = sorted(_sum_by(entries, "store").items(), key=lambda kv: -kv[1])[:TOP_STORES]
    uncategorized = [e for e in entries if e.key == UNCATEGORIZED_KEY]

    return {
        "year": year,
        "month": month,
        "total": total,
        "receipt_total": round(sum(e.amount for e in entries if e.source == "receipt"), 2),
        "bank_only_total": round(sum(e.amount for e in entries if e.source == "bank"), 2),
        "previous_total": round(sum(previous.values()), 2),
        "categories": categories,
        "groups": [
            {"group": g, "amount": round(a, 2), "share_pct": round(a / total * 100, 1) if total > 0 else 0.0}
            for g, a in sorted(groups.items(), key=lambda kv: -kv[1])
        ],
        "owners": [{"owner": o, "amount": a} for o, a in sorted(_sum_by(entries, "owner").items(), key=lambda kv: -kv[1])],
        "stores": [{"store": s, "amount": a} for s, a in store_totals],
        "receipts": {
            "count": len(receipts),
            "average_basket": round(sum(r.total_amount for r in receipts) / len(receipts), 2) if receipts else 0.0,
            "discounts_saved": round(sum(r.total_discount or 0.0 for r in receipts), 2),
        },
        "uncategorized": {"entries": len(uncategorized), "amount": round(sum(e.amount for e in uncategorized), 2)},
        "discrepancies": _discrepancies(db, year, month, first, last),
    }
