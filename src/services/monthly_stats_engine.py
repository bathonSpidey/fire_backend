from models.bank_statement import BankStatement
from services.transaction_classifier import TransactionClassifier


class MonthlyStatsEngine:
    def __init__(self, statements: list[BankStatement]):
        self.statements = statements

    def calculate_month(self, month: str, year: int) -> dict:
        # 1. Run classifier pass
        TransactionClassifier.link_internal_transfers(self.statements)

        gross_income = 0.0
        lifestyle_expenses = 0.0
        fixed_expenses = 0.0
        total_invested = 0.0  # 👈 New wealth tracker accumulator

        category_totals = {}

        for stmt in self.statements:
            if stmt.month != month or stmt.year != year:
                continue

            for tx in stmt.transactions:
                category = tx.category
                amount = tx.amount

                # 1. Ignore linked internal transfers completely (True Shuffling)
                if category in ("INTERNAL_TRANSFER_OUT", "INTERNAL_TRANSFER_IN"):
                    continue

                # 2. Track Investment Execution Orders (True Wealth Building)
                if category == "INVESTMENT_ORDER":
                    if amount < 0:
                        abs_amount = abs(amount)
                        total_invested += abs_amount
                        # Record it in categories, but DO NOT add to lifestyle_expenses
                        category_totals[category] = category_totals.get(category, 0.0) + abs_amount
                    continue

                # 3. Track Standalone Outbound Asset Moves (e.g., Sparkasse Fonds)
                if category == "BANK_TRANSFER":
                    if amount < 0:
                        abs_amount = abs(amount)
                        total_invested += abs_amount
                        category_totals[category] = category_totals.get(category, 0.0) + abs_amount
                    continue

                # 4. Standard Flow: Regular Inflows & Lifestyle Consumption Costs
                if amount > 0:
                    gross_income += amount
                    category_totals[category] = category_totals.get(category, 0.0) + amount
                else:
                    abs_amount = abs(amount)
                    lifestyle_expenses += abs_amount
                    category_totals[category] = category_totals.get(category, 0.0) + abs_amount

                    if category == "FIXED_COSTS":
                        fixed_expenses += abs_amount

        # Calculate metrics using true consumption burn numbers
        net_savings = gross_income - lifestyle_expenses
        savings_rate = round((net_savings / gross_income) * 100, 2) if gross_income > 0 else 0.0

        fixed_ratio = (
            round((fixed_expenses / lifestyle_expenses) * 100) if lifestyle_expenses > 0 else 0
        )
        variable_ratio = 100 - fixed_ratio if lifestyle_expenses > 0 else 0

        # Format Categories Summary
        categories_summary = {}
        for cat, total in category_totals.items():
            denominator = (
                gross_income
                if total > 0 and ("INCOME" in cat or cat == "SALARY")
                else lifestyle_expenses
            )
            categories_summary[cat] = {
                "total": round(total, 2),
                "percentage_of_total": round((total / denominator * 100), 2)
                if denominator > 0
                else 0.0,
            }

        return {
            "month": month,
            "year": year,
            "gross_income": round(gross_income, 2),
            "lifestyle_expenses": round(lifestyle_expenses, 2),
            "net_savings": round(net_savings, 2),
            "savings_rate_pct": savings_rate,
            "total_invested": round(total_invested, 2),  # 👈 Exposes your actual wealth generation!
            "fixed_vs_variable_ratio": f"{fixed_ratio}% Fixed / {variable_ratio}% Variable",
            "categories": categories_summary,
        }
