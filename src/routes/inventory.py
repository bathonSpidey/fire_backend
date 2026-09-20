from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.inventory_db import InventoryDB
from database.session import get_db
from models.inventory import ItemStatusUpdatePayload
from models.inventory_stats import MonthlyInventoryStats
from services.inventory_stats_engine import InventoryStatsEngine

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get(
    "/receipts/monthly-stats", response_model=MonthlyInventoryStats, status_code=status.HTTP_200_OK
)
def get_monthly_inventory_dashboard_stats(
    year: int = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Calculates rich summary analytics, brand loyalty, spending ratios,

    and fresh item decay timelines without triggering slow LLM workloads.
    """
    inventory_db = InventoryDB(db)
    # Reuses the exact eager loading joinedload function we created earlier
    raw_receipts = inventory_db.get_receipts_with_items_by_month(year, month)

    return InventoryStatsEngine.generate_monthly_metrics(year, month, raw_receipts)


@router.put("/item/status", status_code=status.HTTP_200_OK)
def update_individual_item_lifecycle_status(
    payload: ItemStatusUpdatePayload, db: Session = Depends(get_db)
):
    """Updates the tracking status flag of a single inventory item matching

    the item name and original receipt purchase date parameters exactly.
    """
    inventory_db = InventoryDB(db)

    # Execute state change via the case-insensitive database wrapper method
    modified_count = inventory_db.update_item_status_by_name_and_date(
        target_date=payload.purchase_date,
        item_name=payload.item_name,
        new_status=payload.status.value,  # Extracted Enum string value ("Consumed", etc.)
    )

    if modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No inventory item tracked found with the name '{payload.item_name}' "
                f"purchased on date {payload.purchase_date}."
            ),
        )

    db.commit()
    return {
        "status": "Success",
        "detail": f"Successfully updated status to '{payload.status.value}' for {modified_count} item instance(s).",
    }
