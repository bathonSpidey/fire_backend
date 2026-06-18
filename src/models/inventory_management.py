from typing import Optional

from pydantic import BaseModel, Field

from models.inventory import ItemCategory, StorageCondition


class InventoryUpdatePayload(BaseModel):
    name: str | None = None
    brand: str | None = None
    quantity: int | None = Field(None, ge=1)
    unit_cost: float | None = Field(None, ge=0.0)
    category: ItemCategory | None = None
    storage_condition: StorageCondition | None = None
    status: str | None = Field(None, description="e.g., 'Available', 'Consumed', 'Wasted'")
