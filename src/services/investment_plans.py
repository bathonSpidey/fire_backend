"""The household's savings plans: what is bought, how much, how often, from when until when.

A plan is data the household enters (N26 does not say what its buys were). It never changes the
totals, which always come from the statements; later steps use the plans to say what each buy was.

History is never rewritten. Suspending ends a plan, resuming opens a new one, and changing an amount
or instrument closes the old plan the day before and opens a new one: what was true then stays true.
"""

import calendar
import datetime
from dataclasses import dataclass

from sqlalchemy.orm import Session

from database.models import DBInvestmentPlan
from services.investment_brokers import BROKERS

FREQUENCIES = ("weekly", "biweekly", "monthly")
STEP_DAYS = {"weekly": 7, "biweekly": 14}
PER_MONTH = {"weekly": 52 / 12, "biweekly": 26 / 12, "monthly": 1.0}
FREQUENCY_LABEL = {"weekly": "every week", "biweekly": "every two weeks", "monthly": "every month"}


class PlanError(ValueError):
    pass


@dataclass
class PlanIn:
    broker: str
    instrument: str
    amount: float
    frequency: str
    anchor_date: datetime.date | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    note: str | None = None


def _validate(plan: PlanIn) -> PlanIn:
    if plan.broker not in BROKERS:
        raise PlanError(f"Unknown broker '{plan.broker}'. Choose one of {', '.join(BROKERS)}.")
    plan.instrument = (plan.instrument or "").strip()
    if not plan.instrument:
        raise PlanError("Say what the plan buys.")
    if plan.amount is None or plan.amount <= 0:
        raise PlanError("The amount must be more than zero.")
    plan.amount = round(plan.amount, 2)
    if plan.frequency not in FREQUENCIES:
        raise PlanError(f"How often must be one of {', '.join(FREQUENCIES)}.")
    if plan.start_date and plan.end_date and plan.end_date < plan.start_date:
        raise PlanError("A plan cannot end before it starts.")
    plan.note = (plan.note or "").strip() or None
    return plan


def per_month(amount: float, frequency: str) -> float:
    return round(amount * PER_MONTH[frequency], 2)


def execution_dates(plan: DBInvestmentPlan, first: datetime.date, last: datetime.date) -> list[datetime.date]:
    """The days the plan should execute between two dates: needs one known execution day (the anchor).

    Every 2 weeks / every week repeat from the anchor in steps of 14 / 7 days; monthly plans keep the
    anchor's day of the month (a 31st becomes the last day of a shorter month).
    """
    if plan.anchor_date is None or last < first:
        return []
    lo = max(first, plan.start_date) if plan.start_date else first
    hi = min(last, plan.end_date) if plan.end_date else last
    dates: list[datetime.date] = []
    if plan.frequency in STEP_DAYS:
        step = STEP_DAYS[plan.frequency]
        offset = -((plan.anchor_date - lo).days // step)  # ceil: steps from the anchor to the first day >= lo
        day = plan.anchor_date + datetime.timedelta(days=offset * step)
        while day <= hi:
            if day >= lo:
                dates.append(day)
            day += datetime.timedelta(days=step)
        return dates
    year, month = lo.year, lo.month
    while (year, month) <= (hi.year, hi.month):
        day = datetime.date(year, month, min(plan.anchor_date.day, calendar.monthrange(year, month)[1]))
        if lo <= day <= hi:
            dates.append(day)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def status_on(plan: DBInvestmentPlan, day: datetime.date) -> str:
    if plan.start_date and plan.start_date > day:
        return "scheduled"
    if plan.end_date and plan.end_date < day:
        return "ended"
    return "active"


def _view(plan: DBInvestmentPlan, today: datetime.date) -> dict:
    status = status_on(plan, today)
    upcoming = execution_dates(plan, today, today + datetime.timedelta(days=400)) if status != "ended" else []
    return {
        "id": plan.id, "broker": plan.broker, "instrument": plan.instrument, "amount": plan.amount,
        "frequency": plan.frequency, "frequency_label": FREQUENCY_LABEL[plan.frequency],
        "anchor_date": plan.anchor_date.isoformat() if plan.anchor_date else None,
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "end_date": plan.end_date.isoformat() if plan.end_date else None,
        "note": plan.note, "status": status, "per_month": per_month(plan.amount, plan.frequency),
        "next_dates": [d.isoformat() for d in upcoming[:3]],
    }


def list_plans(db: Session, broker: str | None = None, today: datetime.date | None = None) -> dict:
    """Every plan (active first), and what the active ones put in per month."""
    today = today or datetime.date.today()
    query = db.query(DBInvestmentPlan)
    if broker:
        query = query.filter(DBInvestmentPlan.broker == broker)
    rows = list(query)
    plans = [_view(p, today) for p in rows]
    order = {"active": 0, "scheduled": 1, "ended": 2}
    plans.sort(key=lambda p: (order[p["status"]], -p["per_month"], p["instrument"].lower()))
    # Add up the exact monthly amounts and round once: rounding every plan first drifts by cents.
    active = [p for p in rows if status_on(p, today) == "active"]
    exact: dict[str, float] = {}
    for p in active:
        exact[p.broker] = exact.get(p.broker, 0.0) + p.amount * PER_MONTH[p.frequency]
    return {
        "plans": plans,
        "summary": {
            "active": len(active), "ended": sum(1 for p in plans if p["status"] == "ended"),
            "per_month": round(sum(exact.values()), 2),
            "per_month_by_broker": {broker: round(total, 2) for broker, total in exact.items()},
        },
        "instruments": sorted({p["instrument"] for p in plans}, key=str.lower),  # for a pick-list
    }


def _get(db: Session, plan_id: int) -> DBInvestmentPlan:
    plan = db.get(DBInvestmentPlan, plan_id)
    if plan is None:
        raise LookupError(f"No plan #{plan_id}.")
    return plan


def _row(data: PlanIn) -> DBInvestmentPlan:
    return DBInvestmentPlan(
        broker=data.broker, instrument=data.instrument, amount=data.amount, frequency=data.frequency,
        anchor_date=data.anchor_date, start_date=data.start_date, end_date=data.end_date, note=data.note,
    )


def _as_input(plan: DBInvestmentPlan) -> PlanIn:
    return PlanIn(plan.broker, plan.instrument, plan.amount, plan.frequency, plan.anchor_date,
                  plan.start_date, plan.end_date, plan.note)


def create_plan(db: Session, data: PlanIn) -> DBInvestmentPlan:
    plan = _row(_validate(data))
    db.add(plan)
    db.commit()
    return plan


def update_plan(db: Session, plan_id: int, changes: dict) -> DBInvestmentPlan:
    """Correct a plan as entered (a typo, a wrong date). To change what is true from now on, use `change_plan`."""
    plan = _get(db, plan_id)
    data = _as_input(plan)
    for key, value in changes.items():
        if not hasattr(data, key):
            raise PlanError(f"Unknown field '{key}'.")
        setattr(data, key, value)
    _validate(data)
    for key in changes:
        setattr(plan, key, getattr(data, key))  # the validated (trimmed, rounded) value
    db.commit()
    return plan


def suspend_plan(db: Session, plan_id: int, on: datetime.date | None = None) -> DBInvestmentPlan:
    """No execution on or after `on` (default today). The plan stays in the history."""
    plan = _get(db, plan_id)
    on = on or datetime.date.today()
    if plan.end_date is not None and plan.end_date < on:
        raise PlanError("This plan has already ended.")
    last_day = on - datetime.timedelta(days=1)
    if plan.start_date and last_day < plan.start_date:
        raise PlanError("It cannot be suspended before it starts. Delete it instead if it was a mistake.")
    plan.end_date = last_day
    db.commit()
    return plan


def resume_plan(db: Session, plan_id: int, on: datetime.date | None = None) -> DBInvestmentPlan:
    """A suspended plan runs again from `on` (default today), as a new entry: the pause stays in the history."""
    old = _get(db, plan_id)
    on = on or datetime.date.today()
    if old.end_date is None or status_on(old, on) != "ended":
        raise PlanError("Only a plan that has ended can be resumed.")
    data = _as_input(old)
    data.start_date, data.end_date = on, None
    plan = _row(_validate(data))
    db.add(plan)
    db.commit()
    return plan


def change_plan(
    db: Session, plan_id: int, from_date: datetime.date, *, amount: float | None = None,
    frequency: str | None = None, instrument: str | None = None, anchor_date: datetime.date | None = None,
) -> DBInvestmentPlan:
    """From `from_date` the plan is different (a new amount, another rhythm, a rebalance).

    The old plan ends the day before, the new one starts on `from_date`, so the past keeps its truth.
    A new rhythm needs a new known execution day, otherwise the dates cannot be predicted any more.
    """
    old = _get(db, plan_id)
    if old.start_date and from_date <= old.start_date:
        raise PlanError("Pick a day after the plan started (or correct the plan itself).")
    if old.end_date is not None and old.end_date < from_date:
        raise PlanError("This plan has already ended. Resume it instead.")
    data = _as_input(old)
    data.start_date, data.end_date = from_date, None
    data.amount = amount if amount is not None else data.amount
    data.instrument = instrument if instrument is not None else data.instrument
    if frequency is not None and frequency != data.frequency:
        data.frequency, data.anchor_date = frequency, None
    if anchor_date is not None:
        data.anchor_date = anchor_date
    plan = _row(_validate(data))
    old.end_date = from_date - datetime.timedelta(days=1)
    db.add(plan)
    db.commit()
    return plan


def delete_plan(db: Session, plan_id: int) -> None:
    """Remove a plan that should never have been entered (use suspend for one that really ran)."""
    db.delete(_get(db, plan_id))
    db.commit()
