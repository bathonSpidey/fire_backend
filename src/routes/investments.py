from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
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
