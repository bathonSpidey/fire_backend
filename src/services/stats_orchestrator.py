from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBMonthlyStat
from models.bank_statement import BankStatement
from models.bank_transaction import BankTransaction
from services.monthly_stats_engine import MonthlyStatsEngine
from services.period_stats_engine import PeriodStatsEngine

MONTH_MAP = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
INV_MONTH_MAP = {v: k for k, v in MONTH_MAP.items()}


class StatsOrchestrator:
    @staticmethod
    def get_clean_range_stats(start: str, end: str, db: Session) -> dict:
        # 1. Parse date structural formats
        try:
            start_year, start_month_idx = map(int, start.split("-"))
            end_year, end_month_idx = map(int, end.split("-"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Dates must follow YYYY-MM structural formatting."
            )

        # 2. Build explicit list of expected periods
        target_periods = []
        current_year, current_month = start_year, start_month_idx

        start_score = (start_year * 12) + start_month_idx
        end_score = (end_year * 12) + end_month_idx

        if start_score > end_score:
            raise HTTPException(status_code=400, detail="Start range cannot be after end range.")

        while current_year < end_year or (
            current_year == end_year and current_month <= end_month_idx
        ):
            target_periods.append((current_year, INV_MONTH_MAP[current_month]))
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

        # 3. Core Reconciliation Engine
        final_monthly_records = []
        missing_raw_months = []

        for year, month_str in target_periods:
            # Check cached stats first
            stat_record = (
                db.query(DBMonthlyStat)
                .filter(DBMonthlyStat.year == year, DBMonthlyStat.month == month_str)
                .first()
            )

            if stat_record:
                final_monthly_records.append(stat_record.__dict__)
                continue

            # Cache Miss -> Lazy build from DBBankStatement raw uploads
            raw_statements = (
                db.query(DBBankStatement)
                .filter(DBBankStatement.month == month_str, DBBankStatement.year == year)
                .all()
            )

            if not raw_statements:
                missing_raw_months.append(f"{month_str} {year}")
                continue

            # 1. FIX: Explicitly hydrate raw database records into clean Pydantic domain models
            hydrated_statements = []
            for db_stmt in raw_statements:
                # Handle child transactions safely whether they live as a SQLAlchemy
                # relationship model or an internal serialized JSON array block
                parsed_transactions = []
                for tx in db_stmt.transactions:
                    if isinstance(tx, dict):
                        parsed_transactions.append(BankTransaction(**tx))
                    else:
                        # If it's an ORM class model instance, convert it using attributes or model_validate
                        parsed_transactions.append(
                            BankTransaction(
                                date=getattr(tx, "date"),
                                description=getattr(tx, "description"),
                                amount=getattr(tx, "amount"),
                            )
                        )

                hydrated_statements.append(
                    BankStatement(
                        bank=db_stmt.bank,
                        month=db_stmt.month,
                        year=db_stmt.year,
                        starting_balance=db_stmt.starting_balance,
                        closing_balance=db_stmt.closing_balance,
                        transactions=parsed_transactions,
                    )
                )

            # 2. Run your calculation engine using explicitly typed domain objects
            engine = MonthlyStatsEngine(statements=hydrated_statements)
            metrics = engine.calculate_month(month=month_str, year=year)

            # Save newly calculated month back to cache table automatically
            new_cache_entry = DBMonthlyStat(
                month=metrics["month"],
                year=metrics["year"],
                gross_income=metrics["gross_income"],
                lifestyle_expenses=metrics["lifestyle_expenses"],
                net_savings=metrics["net_savings"],
                savings_rate_pct=metrics["savings_rate_pct"],
                total_invested=metrics["total_invested"],
                fixed_vs_variable_ratio=metrics["fixed_vs_variable_ratio"],
                categories=metrics["categories"],
            )
            db.add(new_cache_entry)
            db.commit()

            final_monthly_records.append(metrics)

        # 4. Strict Validation check
        if missing_raw_months:
            readable_gaps = ", ".join(missing_raw_months)
            raise HTTPException(
                status_code=400,
                detail=f"Transaction data missing for: [{readable_gaps}]. Please upload bank statements for these months or adjust your range.",
            )

        # 5. Delegate aggregation to Period Engine
        return PeriodStatsEngine.aggregate_months(final_monthly_records)
