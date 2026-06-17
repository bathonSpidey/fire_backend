from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database.models import DBBankStatement
from database.session import get_db
from models.bank_statement import BankStatement

router = APIRouter(prefix="/statements/manage", tags=["Statement Management"])

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
    statements.sort(key=lambda x: (x.year, MONTH_MAP.get(x.month, 0)), reverse=True)
    return statements


@router.get("/filter/month", response_model=list[BankStatement])
def get_statements_by_month(
    month: str = Query(..., description="Short month name, e.g., 'Apr'"),
    year: int = Query(..., description="Target calendar year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """2. Get all statements matching a specific month and year composite identifier."""
    statements = (
        db.query(DBBankStatement)
        .filter(DBBankStatement.month == month, DBBankStatement.year == year)
        .all()
    )
    return statements


@router.get("/filter/range", response_model=list[BankStatement])
def get_statements_by_range(
    start_month: str = Query(..., description="Start month, e.g., 'Nov'"),
    start_year: int = Query(..., description="Start year, e.g., 2025"),
    end_month: str = Query(..., description="End month, e.g., 'Feb'"),
    end_year: int = Query(..., description="End year, e.g., 2026"),
    db: Session = Depends(get_db),
):
    """3. Get statements within a range that can dynamically span across different calendar years."""
    start_m_idx = MONTH_MAP.get(start_month)
    end_m_idx = MONTH_MAP.get(end_month)

    if not start_m_idx or not end_m_idx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid start or end month abbreviation provided.",
        )

    all_statements = db.query(DBBankStatement).all()

    start_score = (start_year * 12) + start_m_idx
    end_score = (end_year * 12) + end_m_idx

    if start_score > end_score:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start range parameters cannot be chronologically after the End range parameters.",
        )

    filtered_statements = [
        s
        for s in all_statements
        if start_score <= (s.year * 12) + MONTH_MAP.get(s.month, 0) <= end_score
    ]

    filtered_statements.sort(key=lambda x: (x.year, MONTH_MAP.get(x.month, 0)), reverse=True)
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

    db_statement.bank = updated_data.bank
    db_statement.starting_balance = updated_data.starting_balance
    db_statement.closing_balance = updated_data.closing_balance
    db_statement.transactions = [tx.model_dump() for tx in updated_data.transactions]

    db.commit()
    return {"message": f"Successfully updated the statement data parameters for {month} {year}."}


@router.delete("/delete", status_code=status.HTTP_200_OK)
def delete_statement_by_month_and_bank(
    month: str = Query(..., description="Month profile to purge"),
    year: int = Query(..., description="Year profile to purge"),
    bank: str = Query(
        None, description="Optional bank name to isolate delete operation, e.g., 'N26'"
    ),  # 👈 Added optional parameter
    db: Session = Depends(get_db),
):
    """5. Delete statement records targeted by month, year, and optionally isolated by bank name."""
    # 1. Start building standard structural date query base
    query = db.query(DBBankStatement).filter(
        DBBankStatement.month == month, DBBankStatement.year == year
    )

    # 2. Append additional filter only if an explicit bank is specified
    if bank:
        query = query.filter(DBBankStatement.bank == bank)

    # 3. Pull matching entries
    records_to_delete = query.all()

    if not records_to_delete:
        target_info = f"for {month} {year}" + (f" (Bank: {bank})" if bank else "")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No statement entry records located {target_info}.",
        )

    # 4. Loop over matched records to execute deletion block safely
    deleted_count = len(records_to_delete)
    for record in records_to_delete:
        db.delete(record)

    db.commit()

    message = f"Successfully purged {deleted_count} statement record(s) for {month} {year}."
    if bank:
        message = f"Successfully purged {bank} statement record for {month} {year}."

    return {"detail": message}
