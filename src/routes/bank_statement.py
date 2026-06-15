import pathlib
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database.models import DBBankStatement
from database.session import get_db
from models.bank_statement import BankStatement
from readers.statement_orchestrator import StatementOrchestrator

router = APIRouter(prefix="/statements", tags=["Bank Statements"])
TEMP_DIR = pathlib.Path("/tmp/uploaded_statements")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


@router.post(
    "/upload",
    response_model=BankStatement,
    status_code=status.HTTP_200_OK,
    summary="Upload and store a bank statement PDF",
)
async def upload_bank_statement(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only PDF documents are accepted.",
        )

    temp_file_path = TEMP_DIR / file.filename

    try:
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        reader, processor = StatementOrchestrator.get_components(temp_file_path)
        raw_tuples = reader.read()

        # 1. Generate the structured Pydantic object
        structured_statement = processor.process(raw_tuples)

        # 2. Check-then-Act: Check if this specific statement already exists
        existing_statement = (
            db.query(DBBankStatement)
            .filter(
                DBBankStatement.bank == structured_statement.bank,
                DBBankStatement.month == structured_statement.month,
                DBBankStatement.year == structured_statement.year,
            )
            .first()
        )

        serialized_transactions = [tx.model_dump() for tx in structured_statement.transactions]

        if existing_statement:
            # 3a. Idempotent Overwrite Strategy
            existing_statement.starting_balance = structured_statement.starting_balance
            existing_statement.closing_balance = structured_statement.closing_balance
            existing_statement.transactions = serialized_transactions

            # Target object tracking reference for final DB operations
            db_record = existing_statement
        else:
            # 3b. Normal Append Strategy
            db_record = DBBankStatement(
                bank=structured_statement.bank,
                month=structured_statement.month,
                year=structured_statement.year,
                starting_balance=structured_statement.starting_balance,
                closing_balance=structured_statement.closing_balance,
                transactions=serialized_transactions,
            )
            db.add(db_record)

        # 4. Commit and synchronize unit of work changes back to SQLite
        db.commit()
        db.refresh(db_record)

        # 5. Return the clean Pydantic layer contract data validation target
        return structured_statement

    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(val_err))
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while analyzing the statement: {str(err)}",
        )
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()
