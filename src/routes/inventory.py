import os
import pathlib
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from extractor.inventory_extractor import InventoryExtractor
from models.inventory import GeminiReceiptContract

router = APIRouter(prefix="/inventory", tags=["Inventory Processing Engine"])

# Instantiate the extractor once at module level to reuse the GenAI client session
extractor = InventoryExtractor()


@router.post(
    "/analyze-receipt",
    response_model=GeminiReceiptContract,
    status_code=status.HTTP_200_OK,
    summary="Upload a receipt image or PDF to extract a structured Pydantic dataset",
)
async def analyze_receipt_upload(file: UploadFile = File(...)):
    """
    Accepts an image stream (PNG, JPEG) or a structural PDF document,
    saves it safely to a temporary storage location, runs your multimodal
    Gemini vision parsing pipeline, and returns your exact structured model layer.
    """
    # 1. Enforce strict extension filtering before touching disk
    allowed_extensions = {".png", ".jpg", ".jpeg", ".pdf"}
    file_path_suffix = pathlib.Path(file.filename).suffix.lower()

    if file_path_suffix not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{file_path_suffix}'. Supported parameters: {allowed_extensions}",
        )

    # 2. Setup safe runtime paths
    temp_dir = pathlib.Path("/tmp/smartory_uploads")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file_path = temp_dir / f"uploaded_{file.filename}"

    try:
        # 3. Stream raw file bytes directly to the storage destination
        with temp_file_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 4. Fire the existing verified extraction module logic using the local Path pointer
        structured_receipt_payload = extractor.extract_structured_receipt(temp_file_path)

        return structured_receipt_payload

    except FileNotFoundError as fnf_err:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(fnf_err))
    except Exception as e:
        # Catch unexpected API problems or parsing exceptions cleanly
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Gemini processing failure context: {str(e)}",
        )

    finally:
        # 5. The absolute golden rule: always clean up your temporary disk blocks
        if temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except OSError:
                pass  # Avoid halting the active request if file locks drop late
