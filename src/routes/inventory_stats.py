# src/routes/inventory_stats.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from database.session import get_db
from models.inventory_stats import MonthlyInventoryStats
from services.inventory_stats import InventoryStatsService

router = APIRouter(prefix="/inventory-stats", tags=["Monthly Inventory Stats"])


@router.get(
    "/monthly",
    response_model=MonthlyInventoryStats,
    status_code=status.HTTP_200_OK,
)
def get_monthly_inventory_stats(
    year: int = Query(..., description="Calendar year, e.g. 2026"),
    month: int = Query(..., ge=1, le=12, description="Calendar month 1–12"),
    db: Session = Depends(get_db),
):
    """Monthly grocery stats including spoilage profiles, storage risk correlation,
    discount efficiency, and stock carryover.

    Key improvements over the previous implementation:
    - storage_risk_profiles: per-tier spoilage rate + capital efficiency
      (Kept Cool spoils at 8–12%, Frozen at 0%)
    - spoilage_profile: confirmed waste value + chronic spoiler names,
      not just predicted expiry risk buckets
    - discount_efficiency: savings rate + capture rate, not just total saved
    - stock_carryover: Available items at month-end and their carried value
    - frozen_spend: explicitly surfaced as a zero-spoilage capital efficiency signal
    """
    service = InventoryStatsService(db)
    return service.get_monthly_stats(year=year, month=month)
