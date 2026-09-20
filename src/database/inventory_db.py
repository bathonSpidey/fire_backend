from sqlalchemy import extract
from sqlalchemy.orm import Session, joinedload

# 🔗 Import both classes from your models file
from .models import DBReceipt


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
