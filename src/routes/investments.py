from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.session import get_db
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
