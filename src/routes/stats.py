from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.models import DBBankStatement, DBMonthlyStat
from database.session import get_db
from models.bank_statement import BankStatement
from models.financial_stats import MonthlyStatsResponse
from services.monthly_stats_engine import MonthlyStatsEngine

router = APIRouter(prefix="/stats", tags=["Financial Statistics"])


@router.get("/", response_model=MonthlyStatsResponse)
def get_or_calculate_monthly_stats(
    month: str = Query(..., description="Short month name, e.g., 'Apr'"),
    year: int = Query(..., description="Target calendar year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """
    1. Looks at the database for matching month and year metrics.
    2. If not found, attempts to fetch raw statement rows to compute the stats.
    3. If no raw statement matches are found, returns 404 instruct to upload statements.
    """

    # Step 1: Look up data directly from the processed stats cache table
    cached_stats = (
        db.query(DBMonthlyStat)
        .filter(DBMonthlyStat.month == month, DBMonthlyStat.year == year)
        .first()
    )

    if cached_stats:
        return cached_stats

    # Step 2: Cache Miss. Query raw statements filtered by the exact month/year coordinates
    db_statements = (
        db.query(DBBankStatement)
        .filter(DBBankStatement.month == month, DBBankStatement.year == year)
        .all()
    )

    # Step 3: Throw an intentional 404 block if no source files are registered
    if not db_statements:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No financial statistics found for {month} {year}. "
                "Please upload your bank statement PDFs for this month first to generate data tracks."
            ),
        )

    # Step 4: Re-hydrate rows into standard domain objects
    domain_statements = [
        BankStatement(
            bank=r.bank,
            month=r.month,
            year=r.year,
            starting_balance=r.starting_balance,
            closing_balance=r.closing_balance,
            transactions=r.transactions,
        )
        for r in db_statements
    ]

    # Step 5: Execute computation sequence through the engine
    engine = MonthlyStatsEngine(domain_statements)
    metrics = engine.calculate_month(month=month, year=year)

    # Step 6: Persist structural summary back into your database
    db_stats = DBMonthlyStat(
        month=metrics["month"],
        year=metrics["year"],
        gross_income=metrics["gross_income"],
        lifestyle_expenses=metrics["lifestyle_expenses"],
        net_savings=metrics["net_savings"],
        savings_rate_pct=metrics["savings_rate_pct"],
        fixed_vs_variable_ratio=metrics["fixed_vs_variable_ratio"],
        total_invested=metrics["total_invested"],
        categories=metrics["categories"],
    )

    db.add(db_stats)
    db.commit()
    db.refresh(db_stats)

    return db_stats


@router.put("/update", response_model=MonthlyStatsResponse)
def force_recalculate_monthly_stats(
    month: str = Query(..., description="Short month name, e.g., 'Apr'"),
    year: int = Query(..., description="Target calendar year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """
    Forces a complete structural recalculation for a targeted month and year.
    Useful if rule categories or transaction profiles change.
    """
    # 1. Look for existing source bank statements first
    db_statements = (
        db.query(DBBankStatement)
        .filter(DBBankStatement.month == month, DBBankStatement.year == year)
        .all()
    )

    if not db_statements:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cannot recalculate stats. No raw statement source records found for {month} {year}.",
        )

    # 2. Re-hydrate source tracking records into domain schemas
    domain_statements = [
        BankStatement(
            bank=r.bank,
            month=r.month,
            year=r.year,
            starting_balance=r.starting_balance,
            closing_balance=r.closing_balance,
            transactions=r.transactions,
        )
        for r in db_statements
    ]

    # 3. Purge any stale pre-existing stats entry safely out of the table
    db.query(DBMonthlyStat).filter(
        DBMonthlyStat.month == month, DBMonthlyStat.year == year
    ).delete()

    # 4. Compute pristine metrics via engine
    engine = MonthlyStatsEngine(domain_statements)
    metrics = engine.calculate_month(month=month, year=year)

    # 5. Persist the updated dataset down into the cache table
    db_stats = DBMonthlyStat(
        month=metrics["month"],
        year=metrics["year"],
        gross_income=metrics["gross_income"],
        lifestyle_expenses=metrics["lifestyle_expenses"],
        net_savings=metrics["net_savings"],
        total_invested=metrics["total_invested"],
        savings_rate_pct=metrics["savings_rate_pct"],
        fixed_vs_variable_ratio=metrics["fixed_vs_variable_ratio"],
        categories=metrics["categories"],
    )

    db.add(db_stats)
    db.commit()
    db.refresh(db_stats)

    return db_stats


@router.delete("/delete", status_code=status.HTTP_200_OK)
def delete_monthly_stats_cache(
    month: str = Query(..., description="Month profile parameter to purge"),
    year: int = Query(..., description="Year profile parameter to purge"),
    db: Session = Depends(get_db),
):
    """Permanently deletes calculated metrics for a given month and year coordinates."""
    db_stats = (
        db.query(DBMonthlyStat)
        .filter(DBMonthlyStat.month == month, DBMonthlyStat.year == year)
        .first()
    )

    if not db_stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No calculated stats record located matching coordinates: {month} {year}.",
        )

    db.delete(db_stats)
    db.commit()

    return {"detail": f"Successfully dropped statistical records cache for {month} {year}."}
