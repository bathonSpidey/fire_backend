"""Saying what each investment buy was, from what the household told us.

N26 only writes "payment hold for buy" with an amount and a day. Two things say more:
- the savings plans (what the household runs, and one day each plan is known to execute), and
- what the household typed on a single booking (a manual buy on a dip, a sell).

Order of trust, strongest first: what was typed > what the booking itself names (Commerzbank's WKN) >
a plan's schedule > a plan's amount when only one plan could be meant > "Manual buys" (plans exist but
none explains it) > "Unknown" (no plan covers that day). Nothing here ever changes an amount: the
totals come from the statements. This only labels them.

Matching a plan to a booking uses its schedule: a plan that executes every 14 days from a known day
expects a buy of its amount on those days (a booking may land a few days later). Each expected buy is
paired with at most one booking, the closest one. When two plans run the same amount on the same day the
app cannot tell which booking is which, but each instrument still gets exactly one buy: the totals per
instrument stay right.
"""

import datetime
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

from database.models import DBInvestmentPlan
from services.investment_brokers import MANUAL, UNKNOWN
from services.investment_plans import execution_dates, status_on

WINDOW_DAYS = 3  # a booking within this many days of an expected execution counts for it
AMOUNT_EPS = 0.005


@dataclass
class Resolution:
    instrument: str
    source: str  # booking | manual | plan | plan_amount | manual_buy | ambiguous | unknown
    plan_id: int | None = None
    candidates: list[str] = field(default_factory=list)  # the plans that could all be meant (ambiguous)


def booking_ref(bank: str, date: datetime.date, amount: float, description: str) -> str:
    """A fingerprint of one booking that survives reading its statement again (ids do not)."""
    text = " ".join((description or "").split())
    return hashlib.sha1(f"{bank}|{date.isoformat()}|{amount:.2f}|{text}".encode()).hexdigest()[:16]


def _same(a: float, b: float) -> bool:
    return abs(a - b) < AMOUNT_EPS


def _pair(slots, buys):
    """One booking per expected buy, closest first. Returns {slot index: buy index}."""
    window = datetime.timedelta(days=WINDOW_DAYS)
    options = []
    for si, (plan, day) in enumerate(slots):
        for bi, buy in enumerate(buys):
            gap = abs((buy["date"] - day).days)
            if _same(buy["amount"], plan.amount) and datetime.timedelta(days=gap) <= window:
                options.append((gap, day, plan.id, buy["date"], buy["id"], si, bi))
    options.sort()
    taken_slots: dict[int, int] = {}
    taken_buys: set[int] = set()
    for *_, si, bi in options:
        if si not in taken_slots and bi not in taken_buys:
            taken_slots[si] = bi
            taken_buys.add(bi)
    return taken_slots


def resolve(
    bookings: list[dict],
    plans: list[DBInvestmentPlan],
    assignments: dict[str, str],
    covered_until: dict[str, datetime.date | None],
    today: datetime.date,
) -> tuple[dict[int, Resolution], dict[str, dict]]:
    """`bookings`: dicts with id, broker, date, amount (money in is positive), ref, code, counterparty.
    `assignments`: what the household typed, by booking fingerprint. `covered_until`: per broker, the last
    day its uploaded statements reach (an expected buy after that is not missing, just not uploaded yet).

    Returns (a Resolution for every booking id, and per broker a check of plans against reality).
    """
    out: dict[int, Resolution] = {}
    for b in bookings:
        if b["code"]:
            out[b["id"]] = Resolution(b["counterparty"], "booking")

    by_broker: dict[str, list[DBInvestmentPlan]] = defaultdict(list)
    for plan in plans:
        by_broker[plan.broker].append(plan)

    checks: dict[str, dict] = {}
    for broker, plist in by_broker.items():
        mine = [b for b in bookings if b["broker"] == broker]
        buys = [b for b in mine if b["amount"] > 0 and b["id"] not in out and b["ref"] not in assignments]

        # 1. the schedule of every plan whose execution day is known
        anchored = [p for p in plist if p.anchor_date is not None]
        horizon = min(covered_until.get(broker) or today, today)
        floor = min((b["date"] for b in mine), default=today) - datetime.timedelta(days=WINDOW_DAYS)
        slots = [
            (plan, day) for plan in anchored
            for day in execution_dates(plan, plan.start_date or floor, max(horizon, floor))
        ]
        paired = _pair(slots, buys)
        for si, bi in paired.items():
            plan, _ = slots[si]
            out[buys[bi]["id"]] = Resolution(plan.instrument, "plan", plan.id)

        seen_until = covered_until.get(broker)
        observable = [
            (si, s) for si, s in enumerate(slots)
            if seen_until and s[1] + datetime.timedelta(days=WINDOW_DAYS) <= min(seen_until, today)
        ]
        missed = [
            {"date": s[1].isoformat(), "instrument": s[0].instrument, "amount": s[0].amount, "plan_id": s[0].id}
            for si, s in observable if si not in paired
        ]

        # 2. plans without a known day: only the amount can say, and only when it points at one plan
        unanchored = [p for p in plist if p.anchor_date is None]
        for b in buys:
            if b["id"] in out:
                continue
            fits = [p for p in unanchored if status_on(p, b["date"]) == "active" and _same(p.amount, b["amount"])]
            names = sorted({p.instrument for p in fits})
            if len(names) == 1:
                out[b["id"]] = Resolution(names[0], "plan_amount", fits[0].id)
            elif len(names) > 1:
                out[b["id"]] = Resolution(UNKNOWN, "ambiguous", candidates=names)
            elif any(status_on(p, b["date"]) == "active" for p in plist):
                out[b["id"]] = Resolution(MANUAL, "manual_buy")  # plans run that day, none explains this buy
            # else: no plan covers that day: falls through to "unknown" below

        def with_source(source: str) -> list[dict]:
            return [b for b in buys if b["id"] in out and out[b["id"]].source == source]

        checks[broker] = {
            "expected": len(observable), "matched": len(observable) - len(missed), "missed": missed,
            "anchored_plans": sum(1 for p in anchored if status_on(p, today) == "active"),
            "unanchored_plans": sum(1 for p in unanchored if status_on(p, today) == "active"),
            "manual": _sum(with_source("manual_buy")),
            "ambiguous": _sum(with_source("ambiguous")),
        }

    for b in bookings:
        if b["ref"] in assignments:
            out[b["id"]] = Resolution(assignments[b["ref"]], "manual")
        out.setdefault(b["id"], Resolution(UNKNOWN, "unknown"))
    return out, checks


def _sum(rows: list[dict]) -> dict:
    return {"count": len(rows), "net": round(sum(r["amount"] for r in rows), 2)}
