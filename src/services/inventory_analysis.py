# src/services/inventory_analysis.py
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

# Absolute paths to match your framework boundaries safely
from database.models import DBInventoryItem, DBReceipt


class InventoryAnalysis:
    def __init__(self, db: Session):
        """Initializes the deterministic analysis engine with a live database transaction session."""
        self.db = db

    def _get_rolling_cutoff(self, days: int) -> datetime.date:
        """Helper to compute exact historic matrix boundaries relative to the current calendar date."""
        return datetime.now().date() - timedelta(days=days)

    def get_rolling_staples(
        self, rolling_days: int = 90, min_days: int = 3, min_weeks: int = 2
    ) -> list[dict]:
        """Analyzes historic purchase velocity patterns to identify household essentials/staples.

        Args:
            rolling_days: Lookback window (Default: 90 days / rolling 3-months)
            min_days: Minimum number of unique days the item must have been purchased
            min_weeks: Minimum number of separate calendar weeks the item must span
        """
        cutoff_date = self._get_rolling_cutoff(rolling_days)

        # Pull all historic line items within our rolling evaluation window
        items = (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased >= cutoff_date)
            .all()
        )

        # Track parameters by normalized name title
        # Schema: norm_name -> { unique_dates: set, unique_weeks: set, total_units: int, total_spend: float }
        velocity_map = defaultdict(
            lambda: {"dates": set(), "weeks": set(), "total_quantity": 0, "total_spend": 0.0}
        )

        for item in items:
            # Normalize naming text structures to prevent 'rye bread' vs 'Rye Bread' grouping splinters
            norm_name = item.name.strip().title()
            p_date = item.date_purchased

            # Create a unique ISO string tag for the calendar week (e.g., '2026-W23')
            iso_year, iso_week, _ = p_date.isocalendar()
            week_key = f"{iso_year}-W{iso_week}"

            # Map tracking vectors
            velocity_map[norm_name]["dates"].add(p_date)
            velocity_map[norm_name]["weeks"].add(week_key)
            velocity_map[norm_name]["total_quantity"] += item.quantity
            velocity_map[norm_name]["total_spend"] += item.unit_cost * item.quantity

        staples_summary = []

        for name, metrics in velocity_map.items():
            distinct_days_count = len(metrics["dates"])
            distinct_weeks_count = len(metrics["weeks"])

            # EVALUATION THRESHOLD FILTER
            if distinct_days_count >= min_days and distinct_weeks_count >= min_weeks:
                total_qty = metrics["total_quantity"]
                staples_summary.append(
                    {
                        "name": name,
                        "purchase_frequency_days": distinct_days_count,
                        "distribution_weeks": distinct_weeks_count,
                        "total_units_purchased": total_qty,
                        "average_unit_cost_basis": round(metrics["total_spend"] / total_qty, 2),
                    }
                )

        # Sort items dynamically by purchase frequency descending (most essential first)
        return sorted(staples_summary, key=lambda x: x["purchase_frequency_days"], reverse=True)

    def get_predicted_pantry_deficits(self) -> list[dict]:
        """Cross-references household staples against current stock statuses and expiration

        timelines to compile an automated predictive replenishment shopping checklist.
        """
        # 1. Fetch what this household considers essentials
        staples = self.get_rolling_staples()
        today = datetime.now().date()
        deficit_list = []

        for staple in staples:
            # Query the absolute LATEST chronological entry for this product
            latest_record = (
                self.db.query(DBInventoryItem)
                .filter(func.lower(DBInventoryItem.name) == staple["name"].lower())
                .order_by(DBInventoryItem.date_purchased.desc())
                .first()
            )

            if not latest_record:
                continue

            # TRIGGER 1: Explicit Manual Runout
            if latest_record.status in ["Consumed", "Spoiled", "Discarded"]:
                deficit_list.append(
                    {
                        "name": staple["name"],
                        "deficit_trigger": "MANUAL_STATUS_EXHAUSTION",
                        "last_action_state": latest_record.status,
                        "last_purchased_date": latest_record.date_purchased,
                        "urgency": "CRITICAL",
                    }
                )
                continue

            # TRIGGER 2: Temporal Expiration Breach
            if latest_record.date_expiry and latest_record.date_expiry < today:
                deficit_list.append(
                    {
                        "name": staple["name"],
                        "deficit_trigger": "TEMPORAL_SHELF_LIFE_EXPIRED",
                        "last_action_state": latest_record.status,
                        "last_purchased_date": latest_record.date_purchased,
                        "expiry_date_passed": latest_record.date_expiry,
                        "urgency": "MEDIUM",
                    }
                )

        return deficit_list

    def get_financial_leakage_analysis(self, rolling_days: int = 30) -> dict:
        """Computes the literal cash value loss of inventory items that went bad

        or were thrown out within a rolling time horizon.
        """
        cutoff_date = self._get_rolling_cutoff(rolling_days)

        leaked_items = (
            self.db.query(DBInventoryItem)
            .filter(
                DBInventoryItem.date_purchased >= cutoff_date,
                DBInventoryItem.status.in_(["Spoiled", "Discarded"]),
            )
            .all()
        )

        total_loss = 0.0
        category_losses = defaultdict(float)

        for item in leaked_items:
            loss_amount = item.unit_cost * item.quantity
            total_loss += loss_amount
            category_losses[item.category] += loss_amount

        return {
            "rolling_evaluation_days": rolling_days,
            "total_capital_wasted": round(total_loss, 2),
            "loss_by_category_breakdown": {k: round(v, 2) for k, v in category_losses.items()},
        }

    def get_price_inflation_alerts(self) -> list[dict]:
        """Scans historical item records to identify merchant price spikes on identical products."""
        # Query items grouped by name and store to check pricing timelines
        alerts = []

        # Get all distinct item names we track
        distinct_names = self.db.query(DBInventoryItem.name).distinct().all()

        for (name,) in distinct_names:
            # Fetch records for this item ordered chronologically
            history = (
                self.db.query(DBInventoryItem)
                .filter(func.lower(DBInventoryItem.name) == name.lower())
                .order_by(DBInventoryItem.date_purchased.asc())
                .all()
            )

            if len(history) < 2:
                continue

            first_price = history[0].unit_cost
            latest_price = history[-1].unit_cost

            if latest_price > first_price and first_price > 0:
                percentage_drift = ((latest_price - first_price) / first_price) * 100

                # Only flag significant price moves (e.g., greater than 5% drift)
                if percentage_drift >= 5.0:
                    alerts.append(
                        {
                            "item_name": name.strip().title(),
                            "historical_base_price": round(first_price, 2),
                            "latest_market_price": round(latest_price, 2),
                            "percentage_inflation_drift": round(percentage_drift, 1),
                            "first_tracked_date": history[0].date_purchased,
                            "latest_tracked_date": history[-1].date_purchased,
                        }
                    )

        return sorted(alerts, key=lambda x: x["percentage_inflation_drift"], reverse=True)

    def get_regularly_purchased_essentials(self, lookback_days: int = 180) -> list[dict]:
        """Analyzes historical line-item spacing deltas to classify items bought regularly

        over the months, calculating their consumption intervals without LLM assistance.
        """
        cutoff_date = self._get_rolling_cutoff(lookback_days)

        # 1. Fetch entire historical tracking array within window
        items = (
            self.db.query(DBInventoryItem)
            .filter(DBInventoryItem.date_purchased >= cutoff_date)
            .order_by(DBInventoryItem.date_purchased.asc())
            .all()
        )

        # Group chronological purchase timelines by product identity
        product_timelines = defaultdict(list)
        product_metadata = {}

        for item in items:
            norm_name = item.name.strip().title()
            product_timelines[norm_name].append(item.date_purchased)

            # Cache metadata metrics for reporting structures
            if norm_name not in product_metadata:
                product_metadata[norm_name] = {
                    "category": item.category,
                    "storage_condition": item.storage_condition,
                    "brand": item.brand or "Generic",
                }

        regular_items = []

        for name, dates in product_timelines.items():
            # Filter out single-time or sparse random purchases
            if len(dates) < 3:
                continue

            # Eliminate duplicate entries from the exact same shopping day trip
            unique_dates = sorted(list(set(dates)))
            if len(unique_dates) < 3:
                continue

            # 2. Calculate the average day delta interval between trips
            deltas = []
            for i in range(1, len(unique_dates)):
                delta_days = (unique_dates[i] - unique_dates[i - 1]).days
                deltas.append(delta_days)

            avg_interval_days = sum(deltas) / len(deltas) if deltas else 0

            # Calculate total span to ensure it covers multiple months
            total_span_days = (unique_dates[-1] - unique_dates[0]).days

            # REGULARITY MATRIX: Item must be bought across at least a 30-day structural span
            if total_span_days >= 30 and avg_interval_days > 0:
                # Classify pacing type based on operational timeline velocity
                if avg_interval_days <= 8:
                    pacing_tier = "Weekly Staple"
                elif avg_interval_days <= 16:
                    pacing_tier = "Bi-Weekly Refill"
                else:
                    pacing_tier = "Monthly Cyclical"

                meta = product_metadata[name]

                regular_items.append(
                    {
                        "name": name,
                        "category": meta["category"],
                        "storage_condition": meta["storage_condition"],
                        "brand": meta["brand"],
                        "total_purchases_tracked": len(unique_dates),
                        "average_restock_interval_days": round(avg_interval_days, 1),
                        "consumption_pacing_profile": pacing_tier,
                        "historical_span_days": total_span_days,
                    }
                )

        # Return sorted by consistency span (longest active running essentials first)
        return sorted(regular_items, key=lambda x: x["total_purchases_tracked"], reverse=True)
