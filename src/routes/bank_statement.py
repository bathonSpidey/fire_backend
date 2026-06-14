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
    db: Session = Depends(get_db),  # 👈 Inject the DB session helper dependency
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

        # 2. Map Pydantic data directly into your Alembic-generated SQLAlchemy Table Model
        db_statement = DBBankStatement(
            bank=structured_statement.bank,
            month=structured_statement.month,
            year=structured_statement.year,
            starting_balance=structured_statement.starting_balance,
            closing_balance=structured_statement.closing_balance,
            # Serialize the nested Pydantic transaction objects into simple raw JSON dumps
            transactions=[tx.model_dump() for tx in structured_statement.transactions],
        )

        # 3. Persist the record safely into SQLite
        db.add(db_statement)
        db.commit()
        db.refresh(db_statement)

        # 4. Return the validated Pydantic contract layer
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
