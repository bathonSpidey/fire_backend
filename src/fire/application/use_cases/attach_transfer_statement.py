import logging
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path
from uuid import UUID

from fire.application.use_cases.extract_transactions import (
    ExtractTransactions,
    ExtractTransactionsRequest,
)
from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import DocumentType
from fire.domain.entities.transaction import TransactionType
from fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser

logger = logging.getLogger(__name__)


@dataclass
class AttachTransferStatementRequest:
    user_id: UUID
    transfer_transaction_id: UUID  # the Sparkasse transfer OUT transaction
    account_name: str  # "N26", "Commerzbank", etc.
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date


class AttachTransferStatement:
    """
    Attach an investment/transfer bank statement PDF to a transfer transaction.

    Flow:
    1. Mark the originating transaction as type=TRANSFER with account_name
    2. Ingest the investment PDF
    3. Extract its transactions normally (they belong to the investment account)
    4. Store transfer_document_id on the originating transaction

    The extracted transactions are standalone — they are NOT receipt items.
    They show up in the Banks view grouped by account_name.
    Monthly summary excludes the originating TRANSFER from expense totals.
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

    async def execute(self, request: AttachTransferStatementRequest) -> dict:
        # Verify transfer transaction exists
        transfer_tx = await self._transaction_repo.get_by_id(request.transfer_transaction_id)
        if transfer_tx is None:
            raise ValueError(f"Transaction not found: {request.transfer_transaction_id}")

        # Step 1 — mark originating transaction as TRANSFER
        transfer_tx.transaction_type = TransactionType.TRANSFER
        transfer_tx.transfer_account_name = request.account_name
        await self._transaction_repo.save(transfer_tx)
        logger.info(
            "AttachTransfer: marked tx=%s as TRANSFER to %s",
            request.transfer_transaction_id,
            request.account_name,
        )

        # Step 2 — ingest the investment PDF
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
                document_type=DocumentType.INVESTMENT_STATEMENT,
            )
        )
        logger.info("AttachTransfer: document ingested id=%s", document.id)

        # Step 3 — extract transactions from the investment PDF
        extract = ExtractTransactions(
            document_repo=self._document_repo,
            transaction_repo=self._transaction_repo,
            llm_parser=self._llm_parser,
            file_storage=self._file_storage,
        )
        transactions = await extract.execute(
            ExtractTransactionsRequest(
                document_id=document.id,
                mime_type=request.mime_type,
            )
        )
        logger.info(
            "AttachTransfer: extracted %d transactions from investment PDF", len(transactions)
        )

        # Step 4 — link investment document back to the transfer transaction
        transfer_tx.transfer_document_id = document.id
        await self._transaction_repo.save(transfer_tx)

        return {
            "account_name": request.account_name,
            "document_id": document.id,
            "transactions_extracted": len(transactions),
        }
