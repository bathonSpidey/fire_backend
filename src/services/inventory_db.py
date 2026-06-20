import datetime

from sqlalchemy import extract
from sqlalchemy.orm import Session, joinedload  # ◀️ Added joinedload here

# 🔗 Import BOTH data structures from your models layer
from database.models import DBInventoryItem, DBReceipt


class InventoryDB:
    def __init__(self, db: Session):
        self.db = db

    def get_receipts_with_items_by_month(self, year: int, month: int) -> list[DBReceipt]:
        """Fetches all parent receipts along with their nested child inventory items
        purchased within a targeted calendar month, ordered chronologically (ascending).
        """
        return (
            self.db.query(DBReceipt)
            .options(joinedload(DBReceipt.items))  # ⚡ Eager loading eliminates N+1 query loops
            .filter(
                extract("year", DBReceipt.purchase_date) == year,
                extract("month", DBReceipt.purchase_date) == month,
            )
            .order_by(DBReceipt.purchase_date.asc())  # Chronological ascending sort
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
        """Updates specific attributes for all items purchased on a target date.

        Returns the number of rows modified.
        """
        clean_updates = {k: v for k, v in updated_fields.items() if v is not None}
        if not clean_updates:
            return 0

        affected_rows = (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased == target_date)
            .update(clean_updates, synchronize_session="fetch")
        )

        return affected_rows

    def delete_by_date(self, target_date: datetime.date) -> int:
        """Purges all individual inventory items purchased on a specific date.

        Returns the number of rows removed.
        """
        affected_rows = (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased == target_date)
            .delete(synchronize_session="fetch")
        )

        return affected_rows
