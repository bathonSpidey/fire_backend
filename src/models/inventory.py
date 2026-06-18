from enum import StrEnum
from typing import Optional

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
    OTHER = "Other"


class StorageCondition(StrEnum):
    NORMAL = "Normal"  # Room temperature / Pantry
    KEPT_COOL = "Kept Cool"  # Refrigerator
    FROZEN = "Frozen"  # Deep Freezer


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
