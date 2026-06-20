# src/models/stats.py
from pydantic import BaseModel


class CategoryStat(BaseModel):
    category: str
    total_spend: float
    item_count: int
    percentage_of_total: float


class BrandStat(BaseModel):
    brand: str
    total_spend: float
    item_count: int


class ExpiryMetrics(BaseModel):
    critical_3_days: int  # Expiring within 3 days of purchase
    short_term_7_days: int  # Expiring within 7 days
    stable_long_term: int  # Expiring beyond 7 days or shelf-stable (None)


class MonthlyInventoryStats(BaseModel):
    year: int
    month: int
    total_gross_spend: float
    total_discounts_applied: float
    net_spend: float
    total_receipts_processed: int
    total_items_tracked: int
    average_receipt_value: float
    storage_distribution: dict[str, int]  # e.g., {"Normal": 10, "Kept Cool": 4}
    categories: list[CategoryStat]
    top_brands: list[BrandStat]
    spoiled_risk_profile: ExpiryMetrics
