"""Investments: how much really went into the market, read from the bank statements.

The statements are the truth about money that moved. This module only adds up bookings the reader
already marked as `investment` (buys are money out, sells are money back), per broker, month and year.
Profit and loss are not known and are never estimated.

What was bought is only known when the booking says so. Commerzbank names the fund and its WKN in
every savings-plan booking. N26 only says "payment hold for buy", so those stay `Unknown` until the
household says what they were (a later step).
"""

import datetime
import re
from collections import defaultdict

from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction
from services.statement_store import MONTH_ABBR, sync_statement_json

BROKERS = ("N26", "Commerzbank", "Sparkasse")  # banks that can hold investment bookings
ALWAYS_LISTED = ("N26", "Commerzbank")  # tabs that exist even before their first booking
UNKNOWN = "Unknown"
RECEIVED_KINDS = ("income", "refund")  # dividends and tax refunds paid into the depot account
COST_KINDS = ("fee", "spend")  # account fees and taxes on the depot

_WKN = re.compile(r"WPKNR:\s*([A-Z0-9]{6})")
_ISIN = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")


# What the household set by hand on a booking the reader took for an investment (money moving into a
# depot is a transfer between own accounts; the buys themselves are booked on the depot's statement).
MANUAL_REASON = "set by household: not an investment"
TRANSFER = "internal_transfer"


class InvestmentError(ValueError):
    pass


def instrument_code(description: str) -> str | None:
    """The WKN or ISIN a booking names, if it names one (Commerzbank does, N26 does not)."""
    text = description or ""
    found = _WKN.search(text) or _ISIN.search(text)
    return found.group(1) if found else None


def _is_investing_row(bank: str, tx: DBBankTransaction) -> bool:
    """Whether a non-investment booking on this statement belongs to the depot, not to daily life."""
    if bank == "Commerzbank":
        return True  # the whole account exists for the depot
    if bank == "N26":
        return "equities" in f"{tx.counterparty} {tx.description}".lower()
    return False


def _month_start(day: datetime.date) -> tuple[int, int]:
    return day.year, day.month


def _months_between(first: tuple[int, int], last: tuple[int, int]) -> list[tuple[int, int]]:
    out, (year, month) = [], first
    while (year, month) <= last:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _statement_months(db: Session) -> dict[tuple[int, int], set[str]]:
    """Which brokers have a statement for which month. A month without one is 'not uploaded yet',
    which is not the same as 'nothing invested', so it must not pull averages down."""
    covered: dict[tuple[int, int], set[str]] = defaultdict(set)
    for bank, month, year in db.query(DBBankStatement.bank, DBBankStatement.month, DBBankStatement.year):
        if bank in BROKERS and month in MONTH_ABBR:
            covered[(year, MONTH_ABBR.index(month) + 1)].add(bank)
    return covered


def _bookings(db: Session, broker: str | None) -> list[dict]:
    query = (
        db.query(DBBankTransaction, DBBankStatement.bank)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(DBBankTransaction.kind == "investment", DBBankStatement.bank.in_(BROKERS))
    )
    if broker:
        query = query.filter(DBBankStatement.bank == broker)
    rows = []
    for tx, bank in query.order_by(DBBankTransaction.booking_date, DBBankTransaction.id):
        code = instrument_code(tx.description)
        rows.append({
            "id": tx.id, "broker": bank, "date": tx.booking_date,
            "amount": round(-tx.amount, 2),  # money INTO the market is positive, a sell is negative
            "counterparty": tx.counterparty, "description": tx.description,
            "instrument": tx.counterparty if code else UNKNOWN, "code": code,
        })
    return rows


def _around_the_depot(db: Session, broker: str | None) -> tuple[list[dict], list[dict]]:
    """Costs (fees, taxes) and money received (dividends, tax refunds) that belong to the depots."""
    query = db.query(DBBankTransaction, DBBankStatement.bank).join(
        DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id
    ).filter(DBBankStatement.bank.in_(BROKERS), DBBankTransaction.kind != "investment")
    if broker:
        query = query.filter(DBBankStatement.bank == broker)
    costs, received = [], []
    for tx, bank in query.order_by(DBBankTransaction.booking_date):
        if not _is_investing_row(bank, tx):
            continue
        item = {"broker": bank, "date": tx.booking_date.isoformat(), "amount": round(abs(tx.amount), 2),
                "text": (tx.description or tx.counterparty)[:90]}
        if tx.kind in RECEIVED_KINDS and tx.amount > 0:
            received.append(item)
        elif tx.kind in COST_KINDS and tx.amount < 0 and (tx.kind == "fee" or tx.category == "taxes_fees"):
            costs.append(item)
    return costs, received


def _year_rows(months: list[dict]) -> list[dict]:
    by_year: dict[int, dict] = defaultdict(lambda: {"net": 0.0, "bought": 0.0, "sold": 0.0, "count": 0})
    for m in months:
        y = by_year[m["year"]]
        y["net"] += m["net"]
        y["bought"] += m["bought"]
        y["sold"] += m["sold"]
        y["count"] += m["count"]
    rows = []
    for year in sorted(by_year):
        covered = sum(1 for m in months if m["year"] == year and m["covered"])
        y = by_year[year]
        rows.append({
            "year": year, "net": round(y["net"], 2), "bought": round(y["bought"], 2), "sold": round(y["sold"], 2),
            "count": y["count"], "months": covered,
            "avg_per_month": round(y["net"] / covered, 2) if covered else 0.0,
        })
    return rows


def _moved_out(db: Session, broker: str | None) -> list[dict]:
    """Bookings the household took out of the investments by hand (so they can bring them back)."""
    query = (
        db.query(DBBankTransaction, DBBankStatement.bank)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(
            DBBankStatement.bank.in_(BROKERS), DBBankTransaction.kind == TRANSFER,
            DBBankTransaction.transfer_group.is_(None), DBBankTransaction.link_reason == MANUAL_REASON,
        )
    )
    if broker:
        query = query.filter(DBBankStatement.bank == broker)
    return [
        {"id": tx.id, "broker": bank, "date": tx.booking_date.isoformat(), "amount": round(-tx.amount, 2),
         "text": (tx.description or tx.counterparty)[:90]}
        for tx, bank in query.order_by(DBBankTransaction.booking_date)
    ]


def set_booking_kind(db: Session, tx_id: int, kind: str) -> DBBankTransaction:
    """Move a booking between 'investment' and 'transfer between my own accounts', by hand.

    Only a booking the reader marked as an investment can be moved out, and only one that was moved
    out by hand can be brought back: a transfer the app paired with its other side is left alone.
    (Reading the same statement again starts from the reader's opinion again.)
    """
    tx = db.get(DBBankTransaction, tx_id)
    if tx is None:
        raise LookupError(f"No booking #{tx_id}.")
    if tx.statement.bank not in BROKERS:
        raise InvestmentError("Only bookings on N26, Commerzbank or Sparkasse statements can be changed here.")
    if kind == TRANSFER:
        if tx.kind != "investment":
            raise InvestmentError("Only an investment booking can be marked as a transfer.")
        tx.kind, tx.category = TRANSFER, None
        tx.link_status, tx.link_reason = "confirmed", MANUAL_REASON
    elif kind == "investment":
        if not (tx.kind == TRANSFER and tx.transfer_group is None and tx.link_reason == MANUAL_REASON):
            raise InvestmentError("Only a booking you moved out of the investments can be moved back.")
        tx.kind, tx.link_status, tx.link_reason = "investment", None, None
    else:
        raise InvestmentError("A booking can be an 'investment' or an 'internal_transfer'.")
    db.flush()
    sync_statement_json(db, tx.statement)  # the Statements page reads this copy
    db.commit()
    return tx


def summary(db: Session, broker: str | None = None, today: datetime.date | None = None) -> dict:
    """Everything the investment pages show, for one broker or for all of them (`broker=None`)."""
    if broker is not None and broker not in BROKERS:
        raise InvestmentError(f"Unknown broker '{broker}'. Choose one of {', '.join(BROKERS)}.")
    today = today or datetime.date.today()
    bookings = _bookings(db, broker)
    costs, received = _around_the_depot(db, broker)

    listed = sorted({b["broker"] for b in _bookings(db, None)} | set(ALWAYS_LISTED), key=BROKERS.index)
    per_broker = []
    for name in listed:
        mine = [b for b in bookings if b["broker"] == name] if broker is None else (bookings if name == broker else [])
        per_broker.append({
            "broker": name, "net": round(sum(b["amount"] for b in mine), 2), "bookings": len(mine),
            "unknown": round(sum(b["amount"] for b in mine if b["instrument"] == UNKNOWN), 2),
        })

    months: list[dict] = []
    statements = _statement_months(db)
    first = last = None
    if bookings:
        first, last = _month_start(bookings[0]["date"]), _month_start(today)
        cells: dict[tuple[int, int], dict] = {
            slot: {"net": 0.0, "bought": 0.0, "sold": 0.0, "count": 0,
                   "by_instrument": defaultdict(float), "by_broker": defaultdict(float)}
            for slot in _months_between(first, max(last, _month_start(bookings[-1]["date"])))
        }
        for b in bookings:
            cell = cells[_month_start(b["date"])]
            cell["net"] += b["amount"]
            cell["bought" if b["amount"] > 0 else "sold"] += abs(b["amount"])
            cell["count"] += 1
            cell["by_instrument"][b["instrument"]] += b["amount"]
            cell["by_broker"][b["broker"]] += b["amount"]
        for (year, month), cell in cells.items():
            banks = sorted(
                (b for b in statements.get((year, month), set()) if broker is None or b == broker), key=BROKERS.index
            )
            months.append({
                "year": year, "month": month, "label": f"{MONTH_ABBR[month - 1]} {str(year)[2:]}",
                "statements": banks,
                # Shown as "no statement yet" instead of a zero, and left out of every average.
                "covered": bool(banks) or cell["count"] > 0,
                "net": round(cell["net"], 2), "bought": round(cell["bought"], 2), "sold": round(cell["sold"], 2),
                "count": cell["count"],
                "by_instrument": {k: round(v, 2) for k, v in cell["by_instrument"].items()},
                "by_broker": {k: round(v, 2) for k, v in cell["by_broker"].items()},
            })

    instruments = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for b in bookings:
        grouped[b["code"] or UNKNOWN].append(b)
    total_net = sum(b["amount"] for b in bookings)
    for code, rows in grouped.items():
        net = round(sum(r["amount"] for r in rows), 2)
        buys = [r for r in rows if r["amount"] > 0]
        active_months = {_month_start(r["date"]) for r in rows}
        instruments.append({
            "code": None if code == UNKNOWN else code,
            "name": UNKNOWN if code == UNKNOWN else max({r["instrument"] for r in rows}, key=lambda n: sum(r["instrument"] == n for r in rows)),
            "net": net, "share_pct": round(net / total_net * 100, 1) if total_net else 0.0,
            "buys": len(buys), "first": rows[0]["date"].isoformat(), "last": rows[-1]["date"].isoformat(),
            "per_month": round(net / len(active_months), 2),
            "brokers": sorted({r["broker"] for r in rows}, key=BROKERS.index),
        })
    instruments.sort(key=lambda i: (i["name"] == UNKNOWN, -i["net"]))

    recent = [m for m in months if _shift(today, -12) < (m["year"], m["month"]) <= _month_start(today) and m["covered"]]
    unknown = [b for b in bookings if b["instrument"] == UNKNOWN]
    years = _year_rows(months)
    average = round(sum(m["net"] for m in recent) / len(recent), 2) if recent else 0.0
    if broker is None:
        # A month one broker has not uploaded must not lower another broker's figure: add up the
        # averages of the brokers, each over its own months with a statement.
        parts = [summary(db, name, today) for name in listed]
        average = round(sum(p["totals"]["avg_per_month_12"] for p in parts), 2)
        per_year: dict[int, float] = defaultdict(float)
        for part in parts:
            for row in part["years"]:
                per_year[row["year"]] += row["avg_per_month"]
        for row in years:
            row["avg_per_month"] = round(per_year[row["year"]], 2)
    return {
        "broker": broker,
        "brokers": per_broker,
        "totals": {
            "net": round(total_net, 2),
            "bought": round(sum(b["amount"] for b in bookings if b["amount"] > 0), 2),
            "sold": round(-sum(b["amount"] for b in bookings if b["amount"] < 0), 2),
            "this_year": round(sum(b["amount"] for b in bookings if b["date"].year == today.year), 2),
            "avg_per_month_12": average,
            "months_with_statement": sum(1 for m in months if m["covered"]),
            "bookings": len(bookings),
            "first_date": bookings[0]["date"].isoformat() if bookings else None,
            "last_date": bookings[-1]["date"].isoformat() if bookings else None,
        },
        "years": years,
        "months": months,
        "instruments": instruments,
        "unknown": {"net": round(sum(b["amount"] for b in unknown), 2), "count": len(unknown)},
        "moved_out": _moved_out(db, broker),
        "costs": {"total": round(sum(c["amount"] for c in costs), 2), "items": costs},
        "received": {"total": round(sum(r["amount"] for r in received), 2), "items": received},
        "bookings": [
            {**b, "date": b["date"].isoformat()} for b in reversed(bookings)
        ] if broker else [],
    }


def _shift(day: datetime.date, months: int) -> tuple[int, int]:
    index = day.year * 12 + (day.month - 1) + months
    return index // 12, index % 12 + 1
