import pathlib
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.models import DBInventoryItem, DBReceipt
from extractor.inventory_extractor import InventoryExtractor
from models.inventory import GeminiReceiptContract
from services.transaction_matching_engine import TransactionMatchingEngine


class InventoryLinker:
    def __init__(self, db: Session):
        self.db = db
        self.extractor = InventoryExtractor()
        self.matcher = TransactionMatchingEngine(db)

    def process_and_persist_receipt(self, file_path: pathlib.Path) -> dict:
        """Orchestrates intake pipeline: extracts data, saves items, and kicks off

        the matching engine strategy.
        """
        # 1. Image context extraction
        receipt_payload: GeminiReceiptContract = self.extractor.extract_structured_receipt(
            file_path
        )
        purchase_date_obj = datetime.strptime(receipt_payload.purchase_date, "%Y-%m-%d").date()

        # 2. Add to Receipts
        db_receipt = DBReceipt(
            store_name=receipt_payload.store_name,
            total_amount=receipt_payload.total_amount,
            total_discount=receipt_payload.total_discount,
            purchase_date=purchase_date_obj,
            bank_statement_linked=False,  # Defaults to False until engine says otherwise
        )
        self.db.add(db_receipt)
        self.db.flush()

        # 3. Add individual Stock items
        for item in receipt_payload.items:
            expiry_date = None
            if item.estimated_shelf_life_days is not None:
                expiry_date = purchase_date_obj + timedelta(days=item.estimated_shelf_life_days)

            db_item = DBInventoryItem(
                receipt_id=db_receipt.id,
                name=item.name,
                brand=item.brand,
                quantity=item.quantity,
                unit_cost=item.unit_cost,
                category=item.category.value,
                storage_condition=item.storage_condition.value,
                date_purchased=purchase_date_obj,
                date_expiry=expiry_date,
            )
            self.db.add(db_item)

        # 4. Trigger Domain Matching Engine
        linked_count = self.matcher.reconcile_orphans(target_year=purchase_date_obj.year)

        return {
            "receipt_id": db_receipt.id,
            "merchant": db_receipt.store_name,
            "linked_to_bank_ledger": linked_count > 0,
            "items_count": len(receipt_payload.items),
        }
