"""Spending over time: months side by side, what moved, and how this month is going day by day.

Uses exactly the same entries as the month view (services/spending.py), so the numbers agree
everywhere. A month that has not ended is marked `partial` and is never used as a baseline.
"""

import calendar
import datetime
from collections import defaultdict

from sqlalchemy.orm import Session

from services.categories import UNCATEGORIZED_KEY, category_map
from services.spending import collect_entries
from services.statement_store import MONTH_ABBR

MIN_MOVE_EUR = 10.0  # smaller changes are noise
TOP_MOVERS = 5


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _meta(key: str, cats: dict) -> dict:
    if key == UNCATEGORIZED_KEY or key not in cats:
        return {"label": "Uncategorized", "group": "Other", "fixed": False}
    c = cats[key]
    return {"label": c.label, "group": c.group_name, "fixed": bool(c.fixed)}


def trends(db: Session, months: int, end_year: int, end_month: int, today: datetime.date | None = None) -> dict:
    today = today or datetime.date.today()
    cats = category_map(db, include_inactive=True)
    start_year, start_month = _shift(end_year, end_month, -(months - 1))
    first = datetime.date(start_year, start_month, 1)
    last = datetime.date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])

    slots = [_shift(start_year, start_month, i) for i in range(months)]
    by_cat: dict[tuple[int, int], dict[str, float]] = {slot: defaultdict(float) for slot in slots}
    for entry in collect_entries(db, first, last, cats):
        if entry.date:
            by_cat[(entry.date.year, entry.date.month)][entry.key] += entry.amount

    month_rows = []
    for year, month in slots:
        amounts = {k: round(v, 2) for k, v in by_cat[(year, month)].items()}
        groups: dict[str, float] = defaultdict(float)
        fixed = 0.0
        for key, amount in amounts.items():
            meta = _meta(key, cats)
            groups[meta["group"]] += amount
            fixed += amount if meta["fixed"] else 0.0
        total = round(sum(amounts.values()), 2)
        month_rows.append({
            "year": year, "month": month,
            "label": f"{MONTH_ABBR[month - 1]} {str(year)[2:]}",
            "partial": (year, month) >= (today.year, today.month),
            "total": total, "fixed": round(fixed, 2), "flexible": round(total - fixed, 2),
            "by_category": amounts,
            "by_group": {g: round(v, 2) for g, v in groups.items()},
        })

    # Baseline = finished months that have any data at all (an empty month means "not uploaded").
    finished = [m for m in month_rows if not m["partial"] and m["total"] > 0]
    keys = {k for m in month_rows for k in m["by_category"]}
    categories = []
    for key in keys:
        series = [m["by_category"].get(key, 0.0) for m in month_rows]
        base = [m["by_category"].get(key, 0.0) for m in finished]
        categories.append({
            "key": key, **_meta(key, cats),
            "total": round(sum(series), 2),
            "average": round(sum(base) / len(base), 2) if base else 0.0,
        })
    categories.sort(key=lambda c: -c["total"])

    movers: dict = {"month": None, "up": [], "down": [], "baseline_months": 0}
    if len(finished) >= 2:
        latest, earlier = finished[-1], finished[:-1]
        movers["month"] = latest["label"]
        movers["baseline_months"] = len(earlier)
        changes = []
        for key in keys:
            base = sum(m["by_category"].get(key, 0.0) for m in earlier) / len(earlier)
            now = latest["by_category"].get(key, 0.0)
            if abs(now - base) >= MIN_MOVE_EUR:
                changes.append({
                    "key": key, "label": _meta(key, cats)["label"], "now": round(now, 2), "average": round(base, 2),
                    "change": round(now - base, 2),
                    "change_pct": round((now - base) / base * 100) if base > 0 else None,
                })
        movers["up"] = sorted((c for c in changes if c["change"] > 0), key=lambda c: -c["change"])[:TOP_MOVERS]
        movers["down"] = sorted((c for c in changes if c["change"] < 0), key=lambda c: c["change"])[:TOP_MOVERS]

    return {
        "months": month_rows,
        "categories": categories,
        "groups": sorted({g for m in month_rows for g in m["by_group"]}),
        "movers": movers,
        "average_total": round(sum(m["total"] for m in finished) / len(finished), 2) if finished else 0.0,
        "average_fixed": round(sum(m["fixed"] for m in finished) / len(finished), 2) if finished else 0.0,
    }


def _cumulative(entries, days: int, cutoff: int) -> tuple[list[float], bool]:
    daily = [0.0] * (days + 1)
    has_bank = False
    for e in entries:
        if e.date and e.date.day <= days:
            daily[e.date.day] += e.amount
            has_bank = has_bank or e.source == "bank"
    running, out = 0.0, []
    for day in range(1, cutoff + 1):
        running += daily[day]
        out.append(round(running, 2))
    return out, has_bank


def pace(db: Session, year: int, month: int, today: datetime.date | None = None) -> dict:
    """Running total per day of the month against the month before, to see early if it is going too far."""
    today = today or datetime.date.today()
    cats = category_map(db, include_inactive=True)
    days = calendar.monthrange(year, month)[1]
    py, pm = _shift(year, month, -1)
    prev_days = calendar.monthrange(py, pm)[1]
    current_cut = min(days, today.day) if (year, month) == (today.year, today.month) else days

    entries = collect_entries(db, datetime.date(year, month, 1), datetime.date(year, month, days), cats)
    prev_entries = collect_entries(db, datetime.date(py, pm, 1), datetime.date(py, pm, prev_days), cats)
    current, current_bank = _cumulative(entries, days, current_cut)
    previous, previous_bank = _cumulative(prev_entries, prev_days, prev_days)
    same_day = previous[min(current_cut, prev_days) - 1] if previous and current_cut else 0.0
    return {
        "days": max(days, prev_days),
        "current": current,
        "previous": previous,
        "current_total": current[-1] if current else 0.0,
        "previous_same_day": same_day,
        "previous_total": previous[-1] if previous else 0.0,
        "in_progress": current_cut < days or (year, month) == (today.year, today.month),
        # A month with receipts only cannot be compared fairly with one that has the bank statement.
        "unfair_comparison": previous_bank and not current_bank,
    }
