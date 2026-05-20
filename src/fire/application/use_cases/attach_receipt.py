from dataclasses import dataclass
from datetime import date as Date
from uuid import UUID

from fire.application.use_cases.extract_transactions import (
    ExtractTransactions,
    ExtractTransactionsRequest,
)
from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import DocumentType
from fire.domain.entities.transaction import Transaction
from fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser


@dataclass
class AttachReceiptRequest:
    user_id: UUID
    parent_transaction_id: UUID  # the bank debit this receipt belongs to
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date


class AttachReceipt:
    """
    Use case: attach a receipt image to an existing bank transaction.

    Flow:
    1. Ingest the receipt file (hash, dedup, store)
    2. Extract line items via LLM
    3. Set parent_transaction_id on each line item → links them to the bank debit
    4. Update the parent transaction's receipt_document_id for the UI paperclip icon

    Monthly totals remain correct because GetMonthlySummary skips
    transactions where parent_transaction_id IS NOT NULL.
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
        # Verify parent transaction exists
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

        # Step 2 — extract line items
        extract = ExtractTransactions(
            document_repo=self._document_repo,
            transaction_repo=self._transaction_repo,
            llm_parser=self._llm_parser,
            file_storage=self._file_storage,
        )
        line_items = await extract.execute(
            ExtractTransactionsRequest(
                document_id=document.id,
                mime_type=request.mime_type,
            )
        )

        # Step 3 — link each line item to the parent bank transaction
        linked: list[Transaction] = []
        for item in line_items:
            item.parent_transaction_id = request.parent_transaction_id
            updated = await self._transaction_repo.save(item)
            linked.append(updated)

        # Step 4 — mark the parent as having a receipt attached
        parent.receipt_document_id = document.id
        await self._transaction_repo.save(parent)

        return linked
