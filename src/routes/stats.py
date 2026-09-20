from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.session import get_db
from models.financial_stats import MonthlyStatsResponse
from services.month_metrics import calculate_metrics
from services.statement_store import MONTH_ABBR
from services.stats_orchestrator import StatsOrchestrator

router = APIRouter(prefix="/stats", tags=["Financial Statistics"])


@router.get("/", response_model=MonthlyStatsResponse)
def get_monthly_stats(
    month: str = Query(..., description="Short month name, e.g., 'Apr'"),
    year: int = Query(..., description="Target calendar year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """Dashboard numbers for a month, computed live from receipts and bank statements.

    Spending counts every receipt item and every bank payment that has no receipt (a linked pair
    counts once); income and investments come from the bank statements. A month with only
    receipts is already meaningful; `sources` says what it is based on.
    """
    if month not in MONTH_ABBR:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown month '{month}'. Use e.g. 'Apr'.")
    metrics = calculate_metrics(db, month, year)
    if metrics is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Nothing recorded for {month} {year} yet. Upload receipts or the bank "
                "statement for this month."
            ),
        )
    return metrics


@router.get("/range")
def get_range_stats(
    start: str = Query(None, description="Format: YYYY-MM"),
    end: str = Query(None, description="Format: YYYY-MM"),
    db: Session = Depends(get_db),
):
    if not start or not end:  # default: the last three months that have data
        return StatsOrchestrator.get_recent_stats(db, months=3)
    return StatsOrchestrator.get_clean_range_stats(start, end, db)
