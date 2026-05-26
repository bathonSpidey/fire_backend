import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from fire.api.dependencies import (
    get_document_repo,
    get_file_storage,
    get_ingest_use_case,
    get_parser_factory,
    get_transaction_repo,
)
from fire.api.schemas.document import BalanceEntry, DocumentResponse, UploadResponse
from fire.application.use_cases.extract_transactions import (
    ExtractTransactions,
    ExtractTransactionsRequest,
)
from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import Document, DocumentType
from fire.infrastructure.llm.document_parser_factory import DocumentParserFactory
from fire.infrastructure.repositories.document_repository import DocumentRepository
from fire.infrastructure.repositories.transaction_repository import TransactionRepository

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

_SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
}


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user_id: UUID = Form(...),
    file: UploadFile = File(...),
    document_type: DocumentType = Form(default=DocumentType.UNKNOWN),
    ingest: IngestDocument = Depends(get_ingest_use_case),
    document_repo: DocumentRepository = Depends(get_document_repo),
    transaction_repo: TransactionRepository = Depends(get_transaction_repo),
    file_storage=Depends(get_file_storage),
    parser_factory: DocumentParserFactory = Depends(get_parser_factory),
) -> UploadResponse:
    mime_type = file.content_type or "application/pdf"
    if mime_type not in _SUPPORTED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {mime_type}")

    content = await file.read()

    # Step 1 — ingest: hash, store file, create or return existing Document
    document, is_new = await ingest.execute(
        IngestDocumentRequest(
            user_id=user_id,
            filename=file.filename or "upload",
            content=content,
            mime_type=mime_type,
            upload_date=date.today(),
            document_type=document_type,
        )
    )
    logger.info("upload: document id=%s is_new=%s", document.id, is_new)

    # Step 2 — extract (cleans old transactions first, then re-extracts)
    parser = parser_factory.get_parser_for_mime(mime_type)
    extract = ExtractTransactions(
        document_repo=document_repo,
        transaction_repo=transaction_repo,
        llm_parser=parser,
        file_storage=file_storage,
    )
    transactions = await extract.execute(
        ExtractTransactionsRequest(
            document_id=document.id,
            mime_type=mime_type,
        )
    )

    return UploadResponse(
        document=_to_response(document),
        transactions_extracted=len(transactions),
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    user_id: UUID,
    limit: int = 50,
    offset: int = 0,
    document_repo: DocumentRepository = Depends(get_document_repo),
) -> list[DocumentResponse]:
    documents = await document_repo.list_by_user(user_id, limit=limit, offset=offset)
    return [_to_response(d) for d in documents]


@router.get("/balances", response_model=list[BalanceEntry])
async def list_balances(
    user_id: UUID,
    document_repo: DocumentRepository = Depends(get_document_repo),
) -> list[BalanceEntry]:
    """Return closing balances for all processed documents belonging to a user."""
    docs = await document_repo.get_all_by_user(user_id)
    return [
        BalanceEntry(
            document_id=d.id,
            account_name=d.account_name,
            statement_date=d.statement_date,
            closing_balance=d.closing_balance,
            document_type=d.document_type,
        )
        for d in docs
        if d.closing_balance is not None
    ]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    document_repo: DocumentRepository = Depends(get_document_repo),
) -> DocumentResponse:
    document = await document_repo.get_by_id(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return _to_response(document)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    document_repo: DocumentRepository = Depends(get_document_repo),
    file_storage=Depends(get_file_storage),
) -> None:
    document = await document_repo.get_by_id(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    await document_repo.delete(document_id)


def _to_response(d: Document) -> DocumentResponse:
    return DocumentResponse(
        id=d.id,
        user_id=d.user_id,
        filename=d.filename,
        document_type=d.document_type,
        status=d.status,
        uploaded_at=d.uploaded_at,
        processed_at=d.processed_at,
        error_message=d.error_message,
    )
