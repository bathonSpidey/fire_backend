import logging
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import DocumentType
from fire.domain.entities.transaction import Transaction, TransactionCategory, TransactionType
from fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser

logger = logging.getLogger(__name__)


@dataclass
class AttachReceiptRequest:
    user_id: UUID
    parent_transaction_id: UUID
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date


class AttachReceipt:
    """
    Attach a receipt image to an existing bank transaction.

    Parses the receipt and saves line items with parent_transaction_id
    set before the first and only save — no two-step update needed.
    """

    def __init__(
        self,
        document_repo: IDocumentRepository,
        transaction_repo: ITransactionRepository,
        file_storage: IFileStorage,
        llm_parser: ILLMDocumentParser,
    ) -> None:
        self._document_repo = document_repo
        self._transaction_repo = transaction_repo
        self._file_storage = file_storage
        self._llm_parser = llm_parser

    async def execute(self, request: AttachReceiptRequest) -> list[Transaction]:
        logger.info("AttachReceipt: starting for parent=%s", request.parent_transaction_id)

        # Verify parent exists
        parent = await self._transaction_repo.get_by_id(request.parent_transaction_id)
        if parent is None:
            raise ValueError(f"Transaction not found: {request.parent_transaction_id}")

        # Step 1 — ingest receipt file
        ingest = IngestDocument(
            document_repo=self._document_repo,
            file_storage=self._file_storage,
        )
        document, _ = await ingest.execute(
            IngestDocumentRequest(
                user_id=request.user_id,
                filename=request.filename,
                content=request.content,
                mime_type=request.mime_type,
                upload_date=request.upload_date,
                document_type=DocumentType.RECEIPT,
            )
        )
        logger.info(
            "AttachReceipt: document ingested id=%s path=%s", document.id, document.file_path
        )

        # Step 2 — read file bytes and parse via LLM
        file_bytes = await self._file_storage.read(Path(document.file_path))
        logger.info("AttachReceipt: read %d bytes, parsing via LLM", len(file_bytes))

        result = await self._llm_parser.parse(file_bytes, request.mime_type)
        logger.info("AttachReceipt: LLM returned %d transactions", len(result.transactions))
        logger.info("AttachReceipt: raw LLM response (full): %s", result.raw_llm_response)

        if not result.transactions:
            logger.warning("AttachReceipt: LLM returned 0 transactions — nothing to save")
            parent.receipt_document_id = document.id
            await self._transaction_repo.save(parent)
            return []

        # Step 3 — build entities with parent_transaction_id set immediately
        items: list[Transaction] = []
        for i, extracted in enumerate(result.transactions):
            tx = Transaction.create(
                user_id=request.user_id,
                document_id=document.id,
                date=extracted.date,
                description=extracted.description,
                amount=Decimal(str(extracted.amount)),
                transaction_type=TransactionType(extracted.transaction_type),
                category=TransactionCategory(extracted.category)
                if extracted.category
                else TransactionCategory.OTHER,
                merchant=extracted.merchant,
                parent_transaction_id=request.parent_transaction_id,
            )
            logger.info(
                "AttachReceipt: item[%d] id=%s desc=%s amount=%s parent=%s",
                i,
                tx.id,
                tx.description,
                tx.amount,
                tx.parent_transaction_id,
            )
            items.append(tx)

        # Step 4 — save batch
        logger.info("AttachReceipt: saving %d items via save_batch", len(items))
        saved = await self._transaction_repo.save_batch(items)
        logger.info("AttachReceipt: save_batch returned %d items", len(saved))

        # Verify they were actually persisted
        check = await self._transaction_repo.get_by_parent(request.parent_transaction_id)
        logger.info("AttachReceipt: verification query found %d items in DB", len(check))

        # Step 5 — mark parent as having receipt
        parent.receipt_document_id = document.id
        await self._transaction_repo.save(parent)
        logger.info("AttachReceipt: parent updated with receipt_document_id=%s", document.id)

        # Step 6 — mark document processed
        document.mark_processed()
        await self._document_repo.update(document)

        return saved
