import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from services.month_metrics import calculate_metrics
from services.period_stats_engine import PeriodStatsEngine
from services.statement_store import MONTH_ABBR


def _month_after(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


class StatsOrchestrator:
    @staticmethod
    def get_clean_range_stats(start: str, end: str, db: Session):
        """Aggregate every month from `start` to `end` ('YYYY-MM'); each must have data."""
        try:
            start_year, start_month = map(int, start.split("-"))
            end_year, end_month = map(int, end.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates must follow YYYY-MM structural formatting.")
        if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
            raise HTTPException(status_code=400, detail="Months must be between 01 and 12.")
        if (start_year, start_month) > (end_year, end_month):
            raise HTTPException(status_code=400, detail="Start range cannot be after end range.")

        records, missing = [], []
        year, month = start_year, start_month
        while (year, month) <= (end_year, end_month):
            metrics = calculate_metrics(db, MONTH_ABBR[month - 1], year)
            if metrics is None:
                missing.append(f"{MONTH_ABBR[month - 1]} {year}")
            else:
                records.append(metrics)
            year, month = _month_after(year, month)

        if missing:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Nothing recorded for: [{', '.join(missing)}]. Upload receipts or bank "
                    "statements for these months or adjust your range."
                ),
            )
        return PeriodStatsEngine.aggregate_months(records)

    @staticmethod
    def get_recent_stats(db: Session, months: int = 3):
        """The last `months` calendar months (this one included); months without data are skipped."""
        today = datetime.date.today()
        index = today.year * 12 + today.month - 1
        records = []
        for offset in range(months - 1, -1, -1):
            year, month = divmod(index - offset, 12)
            metrics = calculate_metrics(db, MONTH_ABBR[month], year)
            if metrics is not None:
                records.append(metrics)
        return PeriodStatsEngine.aggregate_months(records)
