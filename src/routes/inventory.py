import os
import pathlib
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

# 🔗 We can safely inspect the DBReceipt model directly here for an early out check
from database.models import DBReceipt
from database.session import get_db
from models.inventory import ItemStatusUpdatePayload
from models.inventory_stats import MonthlyInventoryStats
from services.inventory_db import InventoryDB
from services.inventory_linker import InventoryLinker
from services.inventory_stats_engine import InventoryStatsEngine
from services.transaction_matching_engine import TransactionMatchingEngine

router = APIRouter(prefix="/inventory", tags=["Inventory Pipeline Engine"])


@router.post("/upload-receipt", status_code=status.HTTP_201_CREATED)
async def upload_and_persist_receipt(file: UploadFile = File(...), db: Session = Depends(get_db)):
    # 1. Enforce strict extension filtering boundaries
    allowed_extensions = {".png", ".jpg", ".jpeg", ".pdf"}
    file_path_suffix = pathlib.Path(file.filename).suffix.lower()

    if file_path_suffix not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{file_path_suffix}'.",
        )

    # 2. Setup temporary storage runtime structures
    temp_dir = pathlib.Path("/tmp/smartory_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = temp_dir / f"uploaded_{file.filename}"

    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 🚀 Move the linker instantiation here to fetch the payload first
        inventory_linker = InventoryLinker(db=db)

        # Extract the structured payload out of Gemini first (before writing rows)
        receipt_payload = inventory_linker.extractor.extract_structured_receipt(temp_file_path)
        import datetime

        purchase_date_obj = datetime.datetime.strptime(
            receipt_payload.purchase_date, "%Y-%m-%d"
        ).date()

        # 🛡️ IDEMPOTENCY CHECK: Ensure this exact shopping trip hasn't been scanned yet
        existing_receipt = (
            db.query(DBReceipt)
            .filter(
                DBReceipt.store_name == receipt_payload.store_name,
                DBReceipt.total_amount == receipt_payload.total_amount,
                DBReceipt.purchase_date == purchase_date_obj,
            )
            .first()
        )

        if existing_receipt:
            # Drop an early return or raise an conflict error depending on preference
            # Returning the existing structural info avoids breaking client-side workflows
            return {
                "status": "Skipped (Duplicate Detected)",
                "receipt_id": existing_receipt.id,
                "merchant": existing_receipt.store_name,
                "linked_to_bank_ledger": existing_receipt.bank_statement_linked,
                "message": "This receipt has already been processed and saved.",
            }

        # 3. If it's a completely new unique receipt, pass the file to get processed and linked
        result = inventory_linker.process_and_persist_receipt(temp_file_path)

        # Commit changes if the service returned cleanly without hitting an exception
        db.commit()
        return result

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Pipeline processing failure: {str(e)}",
        )
    finally:
        # 4. Golden Rule: Keep disk storage clear of lingering artifacts
        if temp_file_path.exists():
            os.remove(temp_file_path)


@router.post("/reconcile/force")
def force_reconcile_ledger(year: int = 2026, db: Session = Depends(get_db)):

    engine = TransactionMatchingEngine(db)
    links_fixed = engine.reconcile_orphans(target_year=year)
    db.commit()
    return {"status": "Success", "connections_made": links_fixed}


@router.post("/monthly-sync", status_code=status.HTTP_200_OK)
def trigger_monthly_ledger_sync(
    year: int = Query(..., description="Target execution year, e.g. 2026"),
    month: int = Query(
        ..., ge=1, le=12, description="Target execution numerical month calendar index (1-12)"
    ),
    db: Session = Depends(get_db),
):
    """Triggers a targeted monthly reconciliation pass, matching lone receipts

    against corresponding bank logs loaded for that month.
    """
    engine = TransactionMatchingEngine(db)
    links_established = engine.reconcile_orphans(target_year=year, target_month=month)

    db.commit()
    return {
        "status": "Synchronization phase execution successfully completed.",
        "year": year,
        "month": month,
        "links_established_count": links_established,
    }


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
    payload: ItemStatusUpdatePayload,
    db: Session = Depends(get_db)
):
    """Updates the tracking status flag of a single inventory item matching 

    the item name and original receipt purchase date parameters exactly.
    """
    inventory_db = InventoryDB(db)
    
    # Execute state change via the case-insensitive database wrapper method
    modified_count = inventory_db.update_item_status_by_name_and_date(
        target_date=payload.purchase_date,
        item_name=payload.item_name,
        new_status=payload.status.value  # Extracted Enum string value ("Consumed", etc.)
    )
    
    if modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No inventory item tracked found with the name '{payload.item_name}' "
                f"purchased on date {payload.purchase_date}."
            )
        )
        
    db.commit()
    return {
        "status": "Success",
        "detail": f"Successfully updated status to '{payload.status.value}' for {modified_count} item instance(s)."
    }