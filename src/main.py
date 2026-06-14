import pathlib
import shutil

from fastapi import FastAPI, File, HTTPException, UploadFile, status

from models.bank_statement import BankStatement
from readers.statement_orchestrator import StatementOrchestrator

app = FastAPI(
    title="Bank Statement Parser API",
    description="Clean Architecture API to extract structured data from statement PDFs.",
    version="1.0.0",
)

TEMP_DIR = pathlib.Path("/tmp/uploaded_statements")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


@app.post(
    "/statements/upload",
    response_model=BankStatement,
    status_code=status.HTTP_200_OK,
    summary="Upload a bank statement PDF",
    description="Upload an N26 or Sparkasse PDF statement to receive a completely parsed JSON structure.",
)
async def upload_bank_statement(file: UploadFile = File(...)):
    # 1. Validate that it's a PDF
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type. Only PDF documents are accepted.",
        )

    temp_file_path = TEMP_DIR / file.filename

    try:
        # 2. Securely stream the uploaded file to a temporary storage spot
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 3. Use our Orchestrator to grab the required Reader and Processor pair
        reader, processor = StatementOrchestrator.get_components(temp_file_path)

        # 4. Execute the parsing pipeline seamlessly
        raw_tuples = reader.read()
        structured_statement = processor.process(raw_tuples)

        return structured_statement

    except ValueError as val_err:
        # Catch unsupported bank layouts or validation structural issues safely
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(val_err))
    except Exception as err:
        # Fallback security capture block for unexpected systems errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while analyzing the statement: {str(err)}",
        )
    finally:
        # 5. Always clean up temporary system storage tracks after handling a request
        if temp_file_path.exists():
            temp_file_path.unlink()
