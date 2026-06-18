import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from database.inventory_db import InventoryDB
from database.models import DBReceipt
from database.session import get_db
from models.inventory_management import InventoryUpdatePayload

router = APIRouter(prefix="/inventory-management", tags=["Inventory Engine"])


# --- RUD Endpoints using the new InventoryDB Class ---


@router.get("/filter/month", status_code=status.HTTP_200_OK)
def get_inventory_by_month_view(
    year: int = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    inventory_db = InventoryDB(db)
    return inventory_db.get_by_month(year, month)


@router.get("/receipts/month", status_code=status.HTTP_200_OK)
def get_monthly_receipts_breakdown(
    year: int = Query(..., ge=2020),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Retrieves all shopping receipts matching a year/month layout,

    with every individual purchase item nested neatly inside each receipt object.
    """
    inventory_db = InventoryDB(db)
    return inventory_db.get_receipts_with_items_by_month(year, month)


@router.get("/filter/date", status_code=status.HTTP_200_OK)
def get_inventory_by_date_view(
    target_date: datetime.date = Query(...), db: Session = Depends(get_db)
):
    inventory_db = InventoryDB(db)
    return inventory_db.get_by_exact_date(target_date)


@router.put("/update/date", status_code=status.HTTP_200_OK)
def update_inventory_batch_by_date(
    payload: InventoryUpdatePayload,
    target_date: datetime.date = Query(...),
    db: Session = Depends(get_db),
):
    inventory_db = InventoryDB(db)

    update_dict = payload.model_dump(exclude_unset=True)
    # Resolve structural enum shapes to raw strings for DB compatibility
    if "category" in update_dict and update_dict["category"]:
        update_dict["category"] = update_dict["category"].value
    if "storage_condition" in update_dict and update_dict["storage_condition"]:
        update_dict["storage_condition"] = update_dict["storage_condition"].value

    modified_count = inventory_db.update_by_date(target_date, update_dict)

    if modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entries found matching date {target_date}.",
        )

    db.commit()
    return {"detail": f"Successfully updated {modified_count} item entries."}


@router.delete("/purge/date", status_code=status.HTTP_200_OK)
def purge_inventory_by_date(target_date: datetime.date = Query(...), db: Session = Depends(get_db)):
    inventory_db = InventoryDB(db)
    deleted_count = inventory_db.delete_by_date(target_date)

    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No entries found matching date {target_date} to delete.",
        )

    db.commit()
    return {"detail": f"Successfully dropped {deleted_count} items."}


# src/routes/inventory.py


@router.delete("/receipts/{receipt_id}", status_code=status.HTTP_200_OK)
def purge_entire_receipt_pipeline(receipt_id: int, db: Session = Depends(get_db)):
    """Deletes a specific receipt coordinate out of the system ledger completely,

    automatically cascade-dropping every individual tracked inventory item tied to it.
    """
    inventory_db = InventoryDB(db)
    success = inventory_db.delete_receipt_by_id(receipt_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Receipt record with ID {receipt_id} could not be located.",
        )

    db.commit()
    return {
        "detail": f"Successfully dropped receipt ID {receipt_id} along with its tracking items."
    }
