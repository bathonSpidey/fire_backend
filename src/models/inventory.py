from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field


class ItemCategory(StrEnum):
    FOOD = "Food"
    DRINKS = "Drinks"
    HARDWARE = "Hardware"
    ELECTRONICS = "Electronics"
    MEDICINE = "Medicine"
    ENTERTAINMENT = "Entertainment"
    TRAVEL = "Travel"
    LIVING = "Living"
    WORK = "Work"
    BOOKS = "Books"
    CLOTHING = "Clothing"
    COSMETICS = "Cosmetics"
    DEPOSIT = "Deposit"  # Pfand: refundable bottle/crate deposit, not a consumable
    OTHER = "Other"


class StorageCondition(StrEnum):
    NORMAL = "Normal"  # Room temperature / Pantry
    KEPT_COOL = "Kept Cool"  # Refrigerator
    FROZEN = "Frozen"  # Deep Freezer


class ItemStatus(StrEnum):
    AVAILABLE = "Available"  # In storage, ready to use
    CONSUMED = "Consumed"  # Successfully used up completely
    SPOILED = "Spoiled"  # Expired/rotted before consumption
    DISCARDED = "Discarded"  # Throw out for non-decay reasons (packaging damage, etc.)


class ReceiptLine(BaseModel):
    """One purchased product line, as submitted through the save_receipt tool."""

    name: str = Field(
        description="Cleaned product name incl. weight/size if printed. If unsure, keep the "
        "printed text rather than guessing."
    )
    quantity: int = Field(default=1, ge=1, description="Units bought (from '3 * 0,59' -> 3)")
    unit_price: float = Field(
        description="Price of ONE unit before any discount line. Negative only for deposit refunds."
    )
    discount: float = Field(
        default=0.0,
        ge=0,
        description="Discount attached to this line as a POSITIVE number (from a line like "
        "'K Card XTRA Rabatt -0,40' directly below the item). 0 if none.",
    )
    spend_category: str = Field(
        description="Category KEY from the CATEGORIES list (e.g. groceries, personal_care, pets). "
        "Categorise every line individually: one receipt can hold several categories."
    )
    storage_condition: StorageCondition
    estimated_shelf_life_days: int | None = Field(
        default=None, ge=0, description="Days it lasts after purchase; null for non-perishables"
    )
    days_once_opened: int | None = Field(
        default=None, ge=0,
        description="Days it stays good AFTER opening (milk 3, yoghurt 4, sauces 14, jam 30, open "
        "cheese 7). Null for things that do not change once opened and for non-food.",
    )
    brand: str | None = None

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.unit_price - self.discount, 2)


class ReceiptSubmission(BaseModel):
    """Everything read off one receipt. Validated in code before it is stored."""

    store_name: str = Field(description="Normalized merchant name, e.g. 'Kaufland', 'Aldi'")
    purchase_date: date = Field(description="Day of purchase, printed on the receipt")
    total_amount: float = Field(description="Final amount paid ('Summe'), after discounts")
    payment_method: str | None = Field(
        default=None, description="As printed, e.g. 'Kaufland Pay', 'EC-Karte', 'Bar'"
    )
    receipt_number: str | None = Field(default=None, description="Bon/receipt number if printed")
    payment_reference: str | None = Field(
        default=None,
        description="Payment transaction id printed on the receipt (e.g. 'Bluecode "
        "Transaktionsnummer DZFE4JVU...'). Used to match the bank booking.",
    )
    items: list[ReceiptLine]
