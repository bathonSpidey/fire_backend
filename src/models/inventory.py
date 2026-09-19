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


class GeminiExtractedItem(BaseModel):
    name: str = Field(
        description="Cleaned, recognizable product name in English or German (e.g., 'Cornflakes' instead of 'n Flakes')"
    )
    quantity: int = Field(default=1, description="Quantity of the item purchased")
    unit_cost: float = Field(description="The single unit price of the item")
    category: ItemCategory = Field(
        description="The most accurate matching inventory category enum allocation"
    )
    storage_condition: StorageCondition = Field(
        description="Where this item should be stored based on common culinary/household practices"
    )
    estimated_shelf_life_days: int | None = Field(
        None,
        description="Estimated days this product lasts from purchase date given its storage condition. For non-perishables/electronics, leave null.",
    )
    brand: str | None = Field(
        None,
        description="Brand name if explicitly visible on the receipt line (e.g., 'K-Classic', 'Rauch')",
    )
    status: ItemStatus = Field(
        default=ItemStatus.AVAILABLE, description="The current status of the item in the inventory"
    )


class GeminiReceiptContract(BaseModel):
    store_name: str = Field(
        description="Normalized merchant identifier name (e.g., 'Kaufland', 'Lidl', 'Rewe')"
    )
    total_amount: float = Field(
        description="The final total balance paid matching the receipt bottom calculation line"
    )
    total_discount: float | None = Field(
        None, description="The total discount amount applied to the receipt"
    )
    purchase_date: str = Field(
        description="The calendar day the transaction took place. Format: YYYY-MM-DD"
    )
    items: list[GeminiExtractedItem] = Field(
        description="Granular collection array containing itemized product info details"
    )


class ItemStatusUpdatePayload(BaseModel):
    item_name: str = Field(..., description="The name of the target product (case-insensitive)")
    purchase_date: date = Field(..., description="The calendar day the receipt was issued")
    status: ItemStatus = Field(
        ...,
        description="The target lifecycle update state: Available, Consumed, Spoiled, Discarded",
    )


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
    category: ItemCategory
    storage_condition: StorageCondition
    estimated_shelf_life_days: int | None = Field(
        default=None, ge=0, description="Days it lasts after purchase; null for non-perishables"
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
    items: list[ReceiptLine]
