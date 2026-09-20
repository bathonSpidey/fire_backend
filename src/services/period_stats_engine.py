from models.financial_stats import CategorySummary, MonthlyStatsResponse, PeriodStatsResponse


class PeriodStatsEngine:
    @staticmethod
    def aggregate_months(stats: list[MonthlyStatsResponse]) -> PeriodStatsResponse:
        """
        Takes a list of Pydantic MonthlyStatsData objects and flattens
        them into a unified, cross-month macro summary object.
        """
        if not stats:
            return PeriodStatsResponse(
                period_months_count=0,
                gross_income=0.0,
                lifestyle_expenses=0.0,
                net_savings=0.0,
                savings_rate_pct=0.0,
                total_invested=0.0,
                fixed_vs_variable_ratio="0% Fixed / 0% Variable",
                categories={},
            )

        macro_income = 0.0
        macro_lifestyle = 0.0
        macro_invested = 0.0
        macro_fixed = 0.0

        # Tracks running category sums across months
        category_accumulator: dict[str, float] = {}
        category_meta: dict[str, dict] = {}

        for month_data in stats:
            # 1. FIX: Switch from dot-notation to dictionary keys 🔑
            macro_income += month_data["gross_income"]
            macro_lifestyle += month_data["lifestyle_expenses"]
            macro_invested += month_data["total_invested"]

            categories = month_data["categories"]

            # Aggregate category sums safely
            for cat_name, cat_meta in categories.items():
                if cat_meta.get("fixed"):
                    macro_fixed += cat_meta["total"]
                category_accumulator[cat_name] = (
                    category_accumulator.get(cat_name, 0.0) + cat_meta["total"]
                )
                category_meta.setdefault(
                    cat_name, {k: cat_meta.get(k) for k in ("flow", "label", "group", "fixed")}
                )
        # Recalculate Period-Wide Core Metrics
        net_savings = macro_income - macro_lifestyle
        savings_rate = round((net_savings / macro_income) * 100, 2) if macro_income > 0 else 0.0

        fixed_ratio = round((macro_fixed / macro_lifestyle) * 100) if macro_lifestyle > 0 else 0
        variable_ratio = 100 - fixed_ratio if macro_lifestyle > 0 else 0

        # Build formatted CategorySummary sub-objects
        categories_summary: dict[str, CategorySummary] = {}
        for cat, total in category_accumulator.items():
            meta = category_meta[cat]
            denominator = {"income": macro_income, "investment": macro_invested}.get(
                meta.get("flow"), macro_lifestyle
            )
            pct = (total / denominator * 100) if denominator > 0 else 0.0

            categories_summary[cat] = CategorySummary(
                total=round(total, 2),
                percentage_of_total=round(pct, 2),
                flow=meta.get("flow"),
                label=meta.get("label"),
                group=meta.get("group"),
                fixed=bool(meta.get("fixed")),
            )

        # Return a type-validated Pydantic Model instance
        return PeriodStatsResponse(
            period_months_count=len(stats),
            gross_income=round(macro_income, 2),
            lifestyle_expenses=round(macro_lifestyle, 2),
            net_savings=round(net_savings, 2),
            savings_rate_pct=savings_rate,
            total_invested=round(macro_invested, 2),
            fixed_vs_variable_ratio=f"{fixed_ratio}% Fixed / {variable_ratio}% Variable",
            categories=categories_summary,
        )
