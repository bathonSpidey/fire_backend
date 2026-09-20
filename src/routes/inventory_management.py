from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from database.inventory_db import InventoryDB
from database.session import get_db

router = APIRouter(prefix="/inventory-management", tags=["Inventory Engine"])


@router.get("/receipts/month", status_code=status.HTTP_200_OK)
def get_monthly_receipts_breakdown(
    year: int = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """All receipts of a calendar month with every purchased item nested inside (used by the
    Dashboard's Receipts tab, where the items' categories can be edited)."""
    return InventoryDB(db).get_receipts_with_items_by_month(year, month)
