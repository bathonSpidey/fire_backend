from database.models import DBReceipt
from models.inventory_stats import BrandStat, CategoryStat, ExpiryMetrics, MonthlyInventoryStats


class InventoryStatsEngine:
    @staticmethod
    def generate_monthly_metrics(
        year: int, month: int, receipts: list[DBReceipt]
    ) -> MonthlyInventoryStats:
        """Processes a list of raw database receipts to compile high-value

        portfolio metrics without downstream LLM dependencies.
        """
        if not receipts:
            return MonthlyInventoryStats(
                year=year,
                month=month,
                total_gross_spend=0.0,
                total_discounts_applied=0.0,
                net_spend=0.0,
                total_receipts_processed=0,
                total_items_tracked=0,
                average_receipt_value=0.0,
                storage_distribution={},
                categories=[],
                top_brands=[],
                spoiled_risk_profile=ExpiryMetrics(
                    critical_3_days=0, short_term_7_days=0, stable_long_term=0
                ),
            )

        total_gross = 0.0
        total_discount = 0.0
        total_items = 0

        storage_map = {}
        category_map = {}  # category -> {"spend": X, "count": Y}
        brand_map = {}  # brand -> {"spend": X, "count": Y}

        exp_crit = 0
        exp_short = 0
        exp_stable = 0

        for r in receipts:
            total_gross += r.total_amount
            total_discount += r.total_discount or 0.0

            for item in r.items:
                total_items += 1
                item_total_cost = item.unit_cost * item.quantity

                # 1. Storage Condition Breakdown
                storage_map[item.storage_condition] = (
                    storage_map.get(item.storage_condition, 0) + item.quantity
                )

                # 2. Category Aggregations
                cat = item.category
                if cat not in category_map:
                    category_map[cat] = {"spend": 0.0, "count": 0}
                category_map[cat]["spend"] += item_total_cost
                category_map[cat]["count"] += item.quantity

                # 3. Brand Processing
                brand_label = item.brand if item.brand else "Generic/Unbranded"
                if brand_label not in brand_map:
                    brand_map[brand_label] = {"spend": 0.0, "count": 0}
                brand_map[brand_label]["spend"] += item_total_cost
                brand_map[brand_label]["count"] += item.quantity

                # 4. Expiry Risk Vector Metrics
                if item.date_expiry and item.date_purchased:
                    delta = (item.date_expiry - item.date_purchased).days
                    if delta <= 3:
                        exp_crit += item.quantity
                    elif delta <= 7:
                        exp_short += item.quantity
                    else:
                        exp_stable += item.quantity
                else:
                    exp_stable += item.quantity

        net_spend = total_gross - total_discount

        # Format Categories List
        categories_output = [
            CategoryStat(
                category=k,
                total_spend=round(v["spend"], 2),
                item_count=v["count"],
                percentage_of_total=round(
                    (v["spend"] / (net_spend if net_spend > 0 else 1)) * 100, 2
                ),
            )
            for k, v in category_map.items()
        ]
        categories_output.sort(key=lambda x: x.total_spend, reverse=True)

        # Format Brands List (Filter out low spend variants to clean up UI)
        brands_output = [
            BrandStat(brand=k, total_spend=round(v["spend"], 2), item_count=v["count"])
            for k, v in brand_map.items()
        ]
        brands_output.sort(key=lambda x: x.total_spend, reverse=True)

        return MonthlyInventoryStats(
            year=year,
            month=month,
            total_gross_spend=round(total_gross, 2),
            total_discounts_applied=round(total_discount, 2),
            net_spend=round(net_spend, 2),
            total_receipts_processed=len(receipts),
            total_items_tracked=total_items,
            average_receipt_value=round(total_gross / len(receipts), 2),
            storage_distribution=storage_map,
            categories=categories_output,
            top_brands=brands_output[:5],  # Slice out top 5 dominant brands
            spoiled_risk_profile=ExpiryMetrics(
                critical_3_days=exp_crit, short_term_7_days=exp_short, stable_long_term=exp_stable
            ),
        )
