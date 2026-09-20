import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from services import investment_plans as plans
from services import investments

router = APIRouter(prefix="/investments", tags=["Investments"])


@router.get("/summary")
def get_summary(broker: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """How much went into the market: per broker, month and year, and what each instrument received.
    Without `broker` it is the overview of all of them."""
    try:
        return investments.summary(db, broker)
    except investments.InvestmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


class KindIn(BaseModel):
    kind: str  # "internal_transfer" (money moved to my own account) | "investment" (bring it back)


@router.patch("/bookings/{tx_id}")
def change_booking(tx_id: int, body: KindIn, db: Session = Depends(get_db)) -> dict:
    """Decide by hand whether a booking is an investment or a transfer between the household's own accounts."""
    try:
        tx = investments.set_booking_kind(db, tx_id, body.kind)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except investments.InvestmentError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {"id": tx.id, "kind": tx.kind}


# ── savings plans ─────────────────────────────────────────────────────────────────────────────
class PlanBody(BaseModel):
    broker: str
    instrument: str
    amount: float
    frequency: str  # weekly | biweekly | monthly
    anchor_date: datetime.date | None = None  # one known execution day; the others follow from it
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    note: str | None = None


class SuspendBody(BaseModel):
    on: datetime.date | None = None  # no execution on or after this day (default: today)


class ResumeBody(BaseModel):
    on: datetime.date | None = None


class ChangeBody(BaseModel):
    from_date: datetime.date  # from this day the plan is different; the past stays as it was
    amount: float | None = None
    frequency: str | None = None
    instrument: str | None = None
    anchor_date: datetime.date | None = None


def _plan_guard(action):
    try:
        return action()
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except plans.PlanError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


def _one(db: Session, plan) -> dict:
    return next(p for p in plans.list_plans(db)["plans"] if p["id"] == plan.id)


@router.get("/plans")
def list_plans(broker: str | None = Query(None), db: Session = Depends(get_db)) -> dict:
    """Every savings plan (active first) with what the active ones put in per month."""
    return plans.list_plans(db, broker)


@router.post("/plans", status_code=status.HTTP_201_CREATED)
def create_plan(body: PlanBody, db: Session = Depends(get_db)) -> dict:
    return _one(db, _plan_guard(lambda: plans.create_plan(db, plans.PlanIn(**body.model_dump()))))


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, body: dict, db: Session = Depends(get_db)) -> dict:
    """Correct a plan as entered. Send only the fields to change; null clears a date or the note."""
    def parse(key, value):
        return datetime.date.fromisoformat(value) if key.endswith("_date") and value else value

    try:
        changes = {k: parse(k, v) for k, v in body.items()}
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Dates must look like 2026-09-01.")
    return _one(db, _plan_guard(lambda: plans.update_plan(db, plan_id, changes)))


@router.post("/plans/{plan_id}/suspend")
def suspend_plan(plan_id: int, body: SuspendBody, db: Session = Depends(get_db)) -> dict:
    return _one(db, _plan_guard(lambda: plans.suspend_plan(db, plan_id, body.on)))


@router.post("/plans/{plan_id}/resume")
def resume_plan(plan_id: int, body: ResumeBody, db: Session = Depends(get_db)) -> dict:
    """A suspended plan runs again, as a new entry (the pause stays visible in the history)."""
    return _one(db, _plan_guard(lambda: plans.resume_plan(db, plan_id, body.on)))


@router.post("/plans/{plan_id}/change")
def change_plan(plan_id: int, body: ChangeBody, db: Session = Depends(get_db)) -> dict:
    """From a day on the plan is different (new amount, rhythm or instrument): old one ends, new one starts."""
    return _one(db, _plan_guard(lambda: plans.change_plan(
        db, plan_id, body.from_date, amount=body.amount, frequency=body.frequency,
        instrument=body.instrument, anchor_date=body.anchor_date)))


@router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Session = Depends(get_db)) -> None:
    _plan_guard(lambda: plans.delete_plan(db, plan_id))
