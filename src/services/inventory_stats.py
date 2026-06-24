# src/services/inventory_stats.py
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from database.inventory_db import InventoryDB
from database.models import DBInventoryItem, DBReceipt
from models.inventory_stats import (
    BrandStat,
    CategoryStat,
    DiscountEfficiency,
    ExpiryMetrics,
    MonthlyInventoryStats,
    SpoilageProfile,
    StockCarryover,
    StorageRiskProfile,
)


class InventoryStatsService:
    """
    Computes deterministic monthly stats from raw receipt + item records.

    Design note: each _compute_* method is intentionally narrow — one
    responsibility, one return type. This keeps the public entry point
    (get_monthly_stats) readable and makes individual metrics testable
    in isolation without standing up the full pipeline.
    """

    def __init__(self, db: Session):
        self._repo = InventoryDB(db)

    # ── Public entry point ──────────────────────────────────────────────

    def get_monthly_stats(self, year: int, month: int) -> MonthlyInventoryStats:
        receipts = self._repo.get_receipts_with_items_by_month(year, month)
        items = [item for r in receipts for item in r.items]

        gross_spend = sum(r.total_amount for r in receipts)
        total_discounts = sum(r.total_discount for r in receipts)
        item_count = len(items)

        return MonthlyInventoryStats(
            year=year,
            month=month,
            total_gross_spend=round(gross_spend, 2),
            total_discounts_applied=round(total_discounts, 2),
            net_spend=round(gross_spend - total_discounts, 2),
            total_receipts_processed=len(receipts),
            total_items_tracked=item_count,
            average_receipt_value=round(gross_spend / len(receipts), 2) if receipts else 0.0,
            discount_efficiency=self._compute_discount_efficiency(receipts, gross_spend),
            categories=self._compute_category_stats(items, gross_spend),
            top_brands=self._compute_brand_stats(items),
            storage_risk_profiles=self._compute_storage_risk(items),
            spoilage_profile=self._compute_spoilage_profile(items, gross_spend),
            stock_carryover=self._compute_stock_carryover(items),
            frozen_spend=round(
                sum(i.unit_cost * i.quantity for i in items if i.storage_condition == "Frozen"), 2
            ),
            frozen_item_count=sum(1 for i in items if i.storage_condition == "Frozen"),
        )

    # ── Private computation methods ─────────────────────────────────────

    def _compute_discount_efficiency(
        self, receipts: list[DBReceipt], gross_spend: float
    ) -> DiscountEfficiency:
        receipts_with_discounts = sum(1 for r in receipts if r.total_discount > 0)
        total_saved = sum(r.total_discount for r in receipts)
        # gross_before_discounts = what you would have paid without any discounts
        gross_before_discounts = gross_spend + total_saved

        return DiscountEfficiency(
            receipts_with_discounts=receipts_with_discounts,
            total_receipts=len(receipts),
            total_saved=round(total_saved, 2),
            gross_before_discounts=round(gross_before_discounts, 2),
        )

    def _compute_category_stats(
        self, items: list[DBInventoryItem], gross_spend: float
    ) -> list[CategoryStat]:
        category_spend: dict[str, float] = defaultdict(float)
        category_count: dict[str, int] = defaultdict(int)

        for item in items:
            category_spend[item.category] += item.unit_cost * item.quantity
            category_count[item.category] += 1

        return sorted(
            [
                CategoryStat(
                    category=cat,
                    total_spend=round(spend, 2),
                    item_count=category_count[cat],
                    percentage_of_total=round(spend / gross_spend * 100, 1) if gross_spend else 0.0,
                )
                for cat, spend in category_spend.items()
            ],
            key=lambda c: c.total_spend,
            reverse=True,
        )

    def _compute_brand_stats(self, items: list[DBInventoryItem]) -> list[BrandStat]:
        brand_spend: dict[str, float] = defaultdict(float)
        brand_count: dict[str, int] = defaultdict(int)

        for item in items:
            brand = item.brand or "Generic"
            brand_spend[brand] += item.unit_cost * item.quantity
            brand_count[brand] += 1

        return sorted(
            [
                BrandStat(
                    brand=brand,
                    total_spend=round(spend, 2),
                    item_count=brand_count[brand],
                )
                for brand, spend in brand_spend.items()
            ],
            key=lambda b: b.total_spend,
            reverse=True,
        )[:10]

    def _compute_storage_risk(self, items: list[DBInventoryItem]) -> list[StorageRiskProfile]:
        """
        Correlates storage condition with actual spoilage outcome.
        Kept Cool: 8–12% spoilage rate. Frozen: 0%. Normal: 2–4%.
        This replaces the old flat storage_distribution count.
        """
        tiers: dict[str, dict] = defaultdict(
            lambda: {"total": 0, "spoiled": 0, "spend": 0.0, "spoiled_value": 0.0}
        )

        for item in items:
            t = tiers[item.storage_condition]
            value = item.unit_cost * item.quantity
            t["total"] += 1
            t["spend"] += value
            if item.status == "Spoiled":
                t["spoiled"] += 1
                t["spoiled_value"] += value

        return sorted(
            [
                StorageRiskProfile(
                    storage_condition=condition,
                    total_items=m["total"],
                    spoiled_items=m["spoiled"],
                    total_spend=round(m["spend"], 2),
                    spoiled_value=round(m["spoiled_value"], 2),
                )
                for condition, m in tiers.items()
            ],
            key=lambda s: s.spoiled_value,
            reverse=True,
        )

    def _compute_spoilage_profile(
        self, items: list[DBInventoryItem], gross_spend: float
    ) -> SpoilageProfile:
        spoiled = [i for i in items if i.status == "Spoiled"]
        spoiled_value = sum(i.unit_cost * i.quantity for i in spoiled)

        # Chronic spoilers: same item name spoiled more than once this month
        spoiled_name_counts: dict[str, int] = defaultdict(int)
        for i in spoiled:
            spoiled_name_counts[i.name.strip().title()] += 1
        chronic = [name for name, count in spoiled_name_counts.items() if count > 1]

        # Expiry risk buckets — measured from purchase date, not today
        critical = short_term = stable = 0
        for item in items:
            if item.date_expiry is None:
                stable += 1
                continue
            days_until_expiry = (item.date_expiry - item.date_purchased).days
            if days_until_expiry <= 3:
                critical += 1
            elif days_until_expiry <= 7:
                short_term += 1
            else:
                stable += 1

        return SpoilageProfile(
            total_spoiled_items=len(spoiled),
            total_spoiled_value=round(spoiled_value, 2),
            spoilage_rate_pct=round(len(spoiled) / len(items) * 100, 1) if items else 0.0,
            spoilage_cost_rate_pct=round(spoiled_value / gross_spend * 100, 1)
            if gross_spend
            else 0.0,
            expiry_risk=ExpiryMetrics(
                critical_3_days=critical,
                short_term_7_days=short_term,
                stable_long_term=stable,
            ),
            chronic_spoilers=chronic,
        )

    def _compute_stock_carryover(self, items: list[DBInventoryItem]) -> StockCarryover:
        """
        Items still Available at month-end represent deployed capital not yet
        consumed. April: €24.80. May: €69.72. June: €108.57.
        Ignoring this overstates monthly consumption cost.
        """
        available = [i for i in items if i.status == "Available"]
        return StockCarryover(
            available_item_count=len(available),
            carried_value=round(sum(i.unit_cost * i.quantity for i in available), 2),
        )
