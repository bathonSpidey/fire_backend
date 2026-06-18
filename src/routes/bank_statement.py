import pathlib
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database.models import DBBankStatement
from database.session import get_db
from models.bank_statement import BankStatement
from readers.statement_orchestrator import StatementOrchestrator
from services.transaction_matching_engine import TransactionMatchingEngine

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
            # 🛡️ UNCLE BOB EDGE CASE CHECK: Preserve old links during a re-upload overwrite
            # Index current link state by combining unique elements (date, amount, description)
            existing_links = {
                (tx["date"], tx["amount"], tx["description"]): tx.get("inventory_purchase_id")
                for tx in existing_statement.transactions
                if tx.get("inventory_purchase_id") is not None
            }

            # Map existing links back onto the newly parsed transactions list
            for tx in serialized_transactions:
                key = (tx["date"], tx["amount"], tx["description"])
                if key in existing_links:
                    tx["inventory_purchase_id"] = existing_links[key]

            # 3a. Idempotent Overwrite Strategy
            existing_statement.starting_balance = structured_statement.starting_balance
            existing_statement.closing_balance = structured_statement.closing_balance
            existing_statement.transactions = serialized_transactions

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

        # 💡 Force a flush here so the database handles registration parameters,
        # making sure our db_record rows are fully visible to our queries before matching.
        db.flush()

        # 🚀 4. Trigger the Domain Matching Engine
        # It scans backwards for any unlinked inventory items matching this year's timeline.
        matcher = TransactionMatchingEngine(db)
        matcher.reconcile_orphans(target_year=structured_statement.year)

        # 5. Commit and synchronize unit of work changes back to SQLite
        db.commit()
        db.refresh(db_record)

        # 6. Return the clean Pydantic layer contract data validation target
        return structured_statement

    except ValueError as val_err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(val_err))
    except Exception as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while analyzing the statement: {str(err)}",
        )
    finally:
        if temp_file_path.exists():
            temp_file_path.unlink()
