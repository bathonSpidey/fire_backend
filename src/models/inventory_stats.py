# src/models/stats.py
from pydantic import BaseModel, computed_field


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
    critical_3_days: int  # Expiring within 3 days of purchase date
    short_term_7_days: int  # Expiring within 4–7 days
    stable_long_term: int  # Beyond 7 days or shelf-stable (None)


class StorageRiskProfile(BaseModel):
    """
    Correlates each storage tier with its actual spoilage outcome.
    Kept Cool consistently shows 8–12% spoilage rate vs 0% for Frozen.
    Surfaces this signal rather than just counting items per tier.
    """

    storage_condition: str
    total_items: int
    spoiled_items: int
    total_spend: float
    spoiled_value: float

    @computed_field
    @property
    def spoilage_rate_pct(self) -> float:
        if self.total_items == 0:
            return 0.0
        return round((self.spoiled_items / self.total_items) * 100, 1)

    @computed_field
    @property
    def capital_efficiency_pct(self) -> float:
        """Percentage of spend in this storage tier that was NOT wasted."""
        if self.total_spend == 0:
            return 100.0
        return round(((self.total_spend - self.spoiled_value) / self.total_spend) * 100, 1)


class DiscountEfficiency(BaseModel):
    """
    Tracks whether discount opportunities are being captured.
    April: 4.8% savings rate. May: 1.7%. June: 2.9%.
    Declining trend signals fewer promotions being utilized.
    """

    receipts_with_discounts: int
    total_receipts: int
    total_saved: float
    gross_before_discounts: float

    @computed_field
    @property
    def capture_rate_pct(self) -> float:
        """Percentage of receipts where a discount was applied."""
        if self.total_receipts == 0:
            return 0.0
        return round((self.receipts_with_discounts / self.total_receipts) * 100, 1)

    @computed_field
    @property
    def savings_rate_pct(self) -> float:
        """Discount as percentage of gross spend (before discounts)."""
        if self.gross_before_discounts == 0:
            return 0.0
        return round((self.total_saved / self.gross_before_discounts) * 100, 1)


class StockCarryover(BaseModel):
    """
    Items with status=Available at month-end represent capital already deployed
    but not yet consumed. This distorts net monthly consumption if ignored.
    April: €24.80 carried over. May: €69.72. June: €108.57.
    """

    available_item_count: int
    carried_value: float


class SpoilageProfile(BaseModel):
    """
    Extends ExpiryMetrics with actual outcome data — not just predicted risk
    but confirmed waste. Also flags chronic spoilers (same item spoiled 2+ times).
    """

    total_spoiled_items: int
    total_spoiled_value: float
    spoilage_rate_pct: float  # Spoiled items / total items
    spoilage_cost_rate_pct: float  # Spoiled value / gross spend
    expiry_risk: ExpiryMetrics
    # Names of items that spoiled more than once within this month
    chronic_spoilers: list[str]


class MonthlyInventoryStats(BaseModel):
    year: int
    month: int

    # --- Spend summary ---
    total_gross_spend: float
    total_discounts_applied: float
    net_spend: float
    total_receipts_processed: int
    total_items_tracked: int
    average_receipt_value: float

    # --- Discount intelligence ---
    # Replaces bare total_discounts_applied with a structured efficiency view
    discount_efficiency: DiscountEfficiency

    # --- Category breakdown ---
    categories: list[CategoryStat]
    top_brands: list[BrandStat]

    # --- Storage risk (replaces flat storage_distribution dict) ---
    # Previously: {"Normal": 10, "Kept Cool": 4}
    # Now: per-tier spoilage rate, capital efficiency, spoiled value
    storage_risk_profiles: list[StorageRiskProfile]

    # --- Spoilage (replaces spoiled_risk_profile ExpiryMetrics) ---
    # Previously only counted items by expiry window at purchase time.
    # Now includes confirmed waste value and chronic spoiler detection.
    spoilage_profile: SpoilageProfile

    # --- Stock carryover ---
    # Previously invisible — items still Available at month-end
    stock_carryover: StockCarryover

    # --- Frozen capital efficiency ---
    # Frozen items have 0% spoilage rate across all 3 months.
    # Worth surfacing explicitly as a positive allocation signal.
    frozen_spend: float
    frozen_item_count: int
