import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.session import get_db
from services import subscriptions as subs
from services.spending import month_spending
from services.spending_trends import pace, trends

router = APIRouter(prefix="/spending", tags=["Spending"])


class RuleIn(BaseModel):
    frequency: str | None = None  # monthly | quarterly | yearly; empty = as detected
    hidden: bool = False  # not a subscription after all


@router.get("/month")
def get_month_spending(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """Live spending for a month: receipt items by category, bank-only payments filling the gaps,
    and the discrepancies between the two."""
    return month_spending(db, year, month)


@router.get("/trends")
def get_trends(
    months: int = Query(6, ge=2, le=24),
    year: int | None = Query(None, ge=2000, le=2100),
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """Months side by side (per category and group), what changed, up to the given month (default: this one)."""
    today = datetime.date.today()
    return trends(db, months, year or today.year, month or today.month)


@router.get("/pace")
def get_pace(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """Running total by day against the previous month."""
    return pace(db, year, month)


@router.get("/subscriptions")
def get_subscriptions(db: Session = Depends(get_db)) -> dict:
    """Recurring payments found in what was actually paid, with what they cost per month and year."""
    return subs.subscriptions(db)


@router.put("/subscriptions/{key}")
def set_subscription_rule(key: str, body: RuleIn, db: Session = Depends(get_db)) -> dict:
    """Hide a false positive, or say how often it is charged. No frequency and not hidden resets it."""
    try:
        subs.set_rule(db, key, body.frequency or None, body.hidden)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return subs.subscriptions(db)
