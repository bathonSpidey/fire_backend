"""Recurring payments: Netflix, phone, gym, insurance, rent... found from what was actually paid.

Two kinds of evidence, both shown honestly:
- pattern: the same payee, about the same amount, at a regular gap (monthly, quarterly, yearly),
  seen in two or more separate months. It gets stronger as more statements are uploaded.
- category: seen once, but filed under a fixed-cost category (subscriptions, phone, insurance...).
  Assumed monthly until a second payment shows otherwise, and the household can correct it.

The household has the last word (`subscription_rules`): hide a false positive, or set the
frequency. Only money that really left is used: receipts are shopping, not subscriptions, and a
bank booking that a PayPal row explains is replaced by that row (it carries the real merchant name).
"""

import datetime
import re
import statistics
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBBankTransaction, DBSubscriptionRule
from services.categories import category_map
from services.spending import SPEND_KINDS

FREQUENCIES = ("monthly", "quarterly", "yearly")
# (typical days between payments, shortest, longest)
PERIODS = {"monthly": (30.4, 25, 36), "quarterly": (91.0, 80, 100), "yearly": (365.0, 345, 385)}
MONTHS_PER_PERIOD = {"monthly": 1, "quarterly": 3, "yearly": 12}
AMOUNT_TOLERANCE = 0.12  # a price rise of up to 12% is still the same subscription
DUPLICATE_DAYS = 3  # two bookings this close are one payment
ENDED_AFTER = 1.5  # periods without a payment, once statements cover the time, means it ended
BILL_CATEGORIES = {"rent", "loans", "insurance", "utilities", "car_costs", "taxes_fees", "bank_fees"}

_NOISE = re.compile(
    r"\b(gmbh|ag|se|kg|ug|ltd|limited|inc|llc|sarl|bv|co|ohg|ev|sa|paypal|europe|international|com|www|de|eu)\b"
)


def payee_key(name: str) -> str:
    """'Netflix International B.V.' and 'NETFLIX.COM 12345' are the same payee."""
    text = re.sub(r"\b([a-z])\.([a-z])\.", r"\1\2", name.lower())  # "b.v." -> "bv"; "netflix.com" stays two words
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [w for w in _NOISE.sub(" ", text).split() if not w.isdigit()]
    return " ".join(words) or text.strip() or "unknown"


def _slug(key: str) -> str:
    return key.replace(" ", "-")


def monthly_cost(amount: float, frequency: str) -> float:
    return round(amount / MONTHS_PER_PERIOD[frequency], 2)


def _clusters(rows: list[dict]) -> list[list[dict]]:
    """Payments of one payee, grouped by amount (a Netflix and a Netflix-plus-extras stay apart)."""
    clusters: list[list[dict]] = []
    for row in sorted(rows, key=lambda r: r["date"]):
        for cluster in clusters:
            centre = statistics.median(r["amount"] for r in cluster)
            if abs(row["amount"] - centre) <= max(1.0, AMOUNT_TOLERANCE * centre):
                cluster.append(row)
                break
        else:
            clusters.append([row])
    return clusters


def _merge_duplicates(cluster: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for row in cluster:
        if merged and (row["date"] - merged[-1]["date"]).days <= DUPLICATE_DAYS:
            continue
        merged.append(row)
    return merged


def _frequency_of(cluster: list[dict]) -> str | None:
    """The period the gaps between payments fit, if they are regular enough."""
    if len(cluster) < 2:
        return None
    gaps = [(b["date"] - a["date"]).days for a, b in zip(cluster, cluster[1:])]
    median = statistics.median(gaps)
    for name, (_, low, high) in PERIODS.items():
        if low <= median <= high:
            fits = sum(1 for g in gaps if low <= g <= high)
            if fits / len(gaps) >= 0.6:
                return name
    return None


def _payments(db: Session) -> tuple[list[dict], datetime.date | None]:
    rows = (
        db.query(DBBankTransaction, DBBankStatement.bank)
        .join(DBBankStatement, DBBankStatement.id == DBBankTransaction.statement_id)
        .filter(
            DBBankTransaction.kind.in_(SPEND_KINDS),
            DBBankTransaction.amount < 0,
            DBBankTransaction.receipt_id.is_(None),  # shopping with a receipt is not a subscription
        )
        .all()
    )
    explained = {tx.mirror_of for tx, _ in rows if tx.mirror_of}  # bank lines a PayPal row explains
    payments, covered_until = [], None
    for tx, bank in rows:
        if tx.id in explained:
            continue
        date = tx.purchase_date or tx.booking_date
        payments.append({"name": tx.counterparty, "key": payee_key(tx.counterparty), "date": date,
                         "amount": round(-tx.amount, 2), "category": tx.category})
        if bank != "PayPal" and (covered_until is None or tx.booking_date > covered_until):
            covered_until = tx.booking_date
    return payments, covered_until


def _detect(payments: list[dict], cats: dict) -> dict[str, dict]:
    by_payee: dict[str, list[dict]] = defaultdict(list)
    for p in payments:
        by_payee[p["key"]].append(p)

    found: dict[str, dict] = {}
    for key, rows in by_payee.items():
        best = None  # (frequency, cluster): the cluster with the most payments that is regular
        for cluster in _clusters(rows):
            merged = _merge_duplicates(cluster)
            months = {(r["date"].year, r["date"].month) for r in merged}
            frequency = _frequency_of(merged) if len(months) >= 2 else None
            if frequency and (best is None or len(merged) > len(best[1])):
                best = (frequency, merged)
        if best:
            found[key] = {"evidence": "pattern", "frequency": best[0], "payments": best[1]}
            continue
        # Never confirmed: guess from the category, but only for fixed costs.
        fixed_rows = [r for r in rows if (c := cats.get(r["category"] or "")) and c.flow == "expense" and c.fixed]
        if fixed_rows:
            latest = max(fixed_rows, key=lambda r: r["date"])
            cluster = [r for r in fixed_rows if abs(r["amount"] - latest["amount"]) <= max(1.0, AMOUNT_TOLERANCE * latest["amount"])]
            found[key] = {"evidence": "category", "frequency": "monthly", "payments": _merge_duplicates(cluster)}
    return found


def _item(key: str, info: dict, rule: DBSubscriptionRule | None, cats: dict,
          covered_until: datetime.date | None) -> dict:
    payments = info["payments"]
    frequency, evidence = info["frequency"], info["evidence"]
    if rule and rule.frequency in FREQUENCIES:
        frequency, evidence = rule.frequency, "you"
    period = PERIODS[frequency][0]
    last = payments[-1]
    common = Counter(p["category"] for p in payments if p["category"]).most_common(1)
    category_key = common[0][0] if common else None
    category = cats.get(category_key or "")
    first_amount, last_amount = payments[0]["amount"], last["amount"]
    price_change = None
    if len(payments) >= 2 and abs(last_amount - first_amount) > 0.02 * first_amount:
        price_change = {"from": first_amount, "to": last_amount}

    next_expected = last["date"] + datetime.timedelta(days=round(period))
    # "Ended" needs proof: a statement that reaches past when the next payment was due.
    ended = covered_until is not None and covered_until >= last["date"] + datetime.timedelta(days=round(period * ENDED_AFTER))
    name = Counter(p["name"] for p in payments).most_common(1)[0][0]
    return {
        "key": _slug(key),
        "name": name,
        "category_key": category_key,
        "category": category.label if category else "Uncategorized",
        "section": "bill" if category_key in BILL_CATEGORIES else "subscription",
        "amount": last_amount,
        "frequency": frequency,
        "monthly_cost": monthly_cost(last_amount, frequency),
        "yearly_cost": round(monthly_cost(last_amount, frequency) * 12, 2),
        "payments": len(payments),
        "first_date": payments[0]["date"].isoformat(),
        "last_date": last["date"].isoformat(),
        "next_expected": None if ended else next_expected.isoformat(),
        "status": "ended" if ended else "active",
        "evidence": evidence,
        "confidence": "confirmed" if len(payments) >= 3 else "likely" if evidence != "category" else "assumed",
        "price_change": price_change,
        "history": [{"date": p["date"].isoformat(), "amount": p["amount"]} for p in payments[-12:]],
    }


def subscriptions(db: Session) -> dict:
    cats = category_map(db, include_inactive=True)
    payments, covered_until = _payments(db)
    rules = {r.key: r for r in db.query(DBSubscriptionRule)}

    items, hidden = [], []
    for key, info in _detect(payments, cats).items():
        rule = rules.get(_slug(key))
        item = _item(key, info, rule, cats, covered_until)
        if rule and rule.hidden:
            hidden.append({"key": item["key"], "name": item["name"]})
        else:
            items.append(item)
    items.sort(key=lambda i: (i["status"] == "ended", -i["monthly_cost"]))

    active = [i for i in items if i["status"] == "active"]
    monthly = round(sum(i["monthly_cost"] for i in active), 2)
    return {
        "items": items,
        "hidden": hidden,
        "summary": {
            "monthly_total": monthly,
            "yearly_total": round(monthly * 12, 2),
            "active": len(active),
            "assumed_monthly": round(sum(i["monthly_cost"] for i in active if i["confidence"] == "assumed"), 2),
            "subscriptions_monthly": round(sum(i["monthly_cost"] for i in active if i["section"] == "subscription"), 2),
            "bills_monthly": round(sum(i["monthly_cost"] for i in active if i["section"] == "bill"), 2),
            "price_rises": sum(1 for i in active if i["price_change"] and i["price_change"]["to"] > i["price_change"]["from"]),
        },
        "statements_reach": covered_until.isoformat() if covered_until else None,
    }


def set_rule(db: Session, key: str, frequency: str | None, hidden: bool) -> None:
    if frequency is not None and frequency not in FREQUENCIES:
        raise ValueError(f"Frequency must be one of {', '.join(FREQUENCIES)}.")
    rule = db.get(DBSubscriptionRule, key)
    if frequency is None and not hidden:
        if rule:
            db.delete(rule)  # back to what was detected
    elif rule:
        rule.frequency, rule.hidden = frequency, hidden
    else:
        db.add(DBSubscriptionRule(key=key, frequency=frequency, hidden=hidden))
    db.commit()
