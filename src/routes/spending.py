from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database.session import get_db
from services.spending import month_spending

router = APIRouter(prefix="/spending", tags=["Spending"])


@router.get("/month")
def get_month_spending(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """Live spending for a month: receipt items by category, bank-only payments filling the gaps,
    and the discrepancies between the two."""
    return month_spending(db, year, month)
