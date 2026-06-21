import datetime

from sqlalchemy import extract, func
from sqlalchemy.orm import Session, joinedload

# 🔗 Import both classes from your models file
from .models import DBInventoryItem, DBReceipt


class InventoryDB:
    def __init__(self, db: Session):
        self.db = db

    def get_receipts_with_items_by_month(self, year: int, month: int) -> list[DBReceipt]:
        """Fetches all parent receipts along with their nested child inventory items
        purchased within a targeted calendar month, ordered chronologically (ascending).
        """
        return (
            self.db.query(DBReceipt)
            .options(joinedload(DBReceipt.items))
            .filter(
                extract("year", DBReceipt.purchase_date) == year,
                extract("month", DBReceipt.purchase_date) == month,
            )
            .order_by(DBReceipt.purchase_date.asc())  # ◀️ Added chronological ascending sort
            .all()
        )

    def get_by_month(self, year: int, month: int) -> list[DBInventoryItem]:
        """Fetches all flat individual items purchased within a targeted calendar month."""
        return (
            self.db.query(DBInventoryItem)
            .filter(
                extract("year", DBInventoryItem.date_purchased) == year,
                extract("month", DBInventoryItem.date_purchased) == month,
            )
            .all()
        )

    def get_by_exact_date(self, target_date: datetime.date) -> list[DBInventoryItem]:
        """Fetches all items purchased on an exact calendar date."""
        return (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased == target_date)
            .all()
        )

    def update_by_date(self, target_date: datetime.date, updated_fields: dict) -> int:
        """Updates specific attributes for all items purchased on a target date."""
        clean_updates = {k: v for k, v in updated_fields.items() if v is not None}
        if not clean_updates:
            return 0

        return (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased == target_date)
            .update(clean_updates, synchronize_session="fetch")
        )

    def delete_by_date(self, target_date: datetime.date) -> int:
        """Purges all individual inventory items purchased on a specific date."""
        return (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased == target_date)
            .delete(synchronize_session="fetch")
        )

    def delete_receipt_by_id(self, receipt_id: int) -> bool:
        """Purges a single receipt record from the database.

        Due to cascade configuration, all associated inventory items
        mapping back to this receipt are also automatically dropped.
        Returns True if an entry was located and scrubbed, False otherwise.
        """
        receipt = self.db.query(DBReceipt).filter(DBReceipt.id == receipt_id).first()
        if not receipt:
            return False

        self.db.delete(receipt)
        return True

    def update_item_status_by_name_and_date(
        self, target_date: datetime.date, item_name: str, new_status: str
    ) -> int:
        """Updates the tracking status of a specific item matched by its name and
        purchase date. Returns the number of affected rows.
        """
        affected_rows = (
            self.db.query(DBInventoryItem)
            .filter(
                DBInventoryItem.date_purchased == target_date,
                func.lower(DBInventoryItem.name) == item_name.lower().strip(),
            )
            .update({"status": new_status}, synchronize_session="fetch")
        )
        return affected_rows
