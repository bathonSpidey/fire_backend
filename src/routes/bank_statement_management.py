from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import DBBankStatement
from database.session import get_db
from models.bank_statement import BankStatement

router = APIRouter(prefix="/statements/manage", tags=["Statement Management"])

# Simple utility map to convert short English month names to sorting integers
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


@router.get("/", response_model=list[BankStatement])
def get_all_statements(db: Session = Depends(get_db)):
    """1. Get all statements ordered by year and month chronologically (latest first)."""
    statements = db.query(DBBankStatement).all()

    # Python-side sort to accurately handle calendar month strings ("Apr", "Jan")
    statements.sort(key=lambda x: (x.year, MONTH_MAP.get(x.month, 0)), reverse=True)
    return statements


@router.get("/filter/month", response_model=list[BankStatement])
def get_statements_by_month(
    month: str = Query(..., description="Short month name, e.g., 'Apr'"),
    db: Session = Depends(get_db),
):
    """2. Get all statements matching a specific month."""
    statements = db.query(DBBankStatement).filter(DBBankStatement.month == month).all()
    return statements


@router.get("/filter/range", response_model=list[BankStatement])
def get_statements_by_month_range(
    start_month: str = Query(..., description="Start month, e.g., 'Jan'"),
    end_month: str = Query(..., description="End month, e.g., 'Apr'"),
    year: int = Query(..., description="Target calendar year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """3. Get statements within a specific month range for a given year."""
    start_idx = MONTH_MAP.get(start_month)
    end_idx = MONTH_MAP.get(end_month)

    if not start_idx or not end_idx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid start or end month abbreviation provided.",
        )

    # Fetch records for the targeted year
    statements = db.query(DBBankStatement).filter(DBBankStatement.year == year).all()

    # Filter list down to records sitting inside the range limits inclusively
    filtered_statements = [
        s for s in statements if start_idx <= MONTH_MAP.get(s.month, 0) <= end_idx
    ]

    return filtered_statements


@router.put("/update", response_model=dict)
def update_statement_by_month(
    month: str = Query(..., description="Month profile to update"),
    year: int = Query(..., description="Year profile to update"),
    updated_data: BankStatement = None,
    db: Session = Depends(get_db),
):
    """4. Update a particular statement selected by month and year coordinates."""
    if not updated_data:
        raise HTTPException(status_code=400, detail="Missing updated record schema payload.")

    db_statement = (
        db.query(DBBankStatement)
        .filter(DBBankStatement.month == month, DBBankStatement.year == year)
        .first()
    )

    if not db_statement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No bank statement record found for {month} {year}.",
        )

    # Apply changes over individual column fields
    db_statement.bank = updated_data.bank
    db_statement.starting_balance = updated_data.starting_balance
    db_statement.closing_balance = updated_data.closing_balance
    db_statement.transactions = [tx.model_dump() for tx in updated_data.transactions]

    db.commit()
    return {"message": f"Successfully updated the statement data parameters for {month} {year}."}


@router.delete("/delete", status_code=status.HTTP_200_OK)
def delete_statement_by_month(
    month: str = Query(..., description="Month profile to purge"),
    year: int = Query(..., description="Year profile to purge"),
    db: Session = Depends(get_db),
):
    """5. Delete entire statement records for a targeted month and year."""
    db_statement = (
        db.query(DBBankStatement)
        .filter(DBBankStatement.month == month, DBBankStatement.year == year)
        .first()
    )

    if not db_statement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statement entry for {month} {year} could not be located.",
        )

    db.delete(db_statement)
    db.commit()
    return {"detail": f"Successfully purged statement entry records for {month} {year}."}
