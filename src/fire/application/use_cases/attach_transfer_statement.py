import logging
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import DocumentType
from fire.domain.entities.transaction import Transaction, TransactionCategory, TransactionType
from fire.domain.entities.transaction import TransactionType as TxType
from fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser

logger = logging.getLogger(__name__)


@dataclass
class AttachTransferStatementRequest:
    user_id: UUID
    transfer_transaction_id: UUID
    account_name: str
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date


class AttachTransferStatement:
    """
    Attach an investment bank statement to a transfer transaction.

    Parses the PDF and saves investment transactions directly linked to
    the document. The BanksPage finds them via document_id matching.

    Does NOT use ExtractTransactions use case — we call the parser and
    repo directly so we can set user_id correctly on each transaction.
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
        # Verify parent transfer transaction exists
        transfer_tx = await self._transaction_repo.get_by_id(request.transfer_transaction_id)
        if transfer_tx is None:
            raise ValueError(f"Transaction not found: {request.transfer_transaction_id}")

        # Step 1 — mark originating transaction as TRANSFER
        transfer_tx.transaction_type = TransactionType.TRANSFER
        transfer_tx.transfer_account_name = request.account_name
        await self._transaction_repo.save(transfer_tx)
        logger.info("AttachTransfer: marked tx=%s as TRANSFER to %s",
                    request.transfer_transaction_id, request.account_name)

        # Step 2 — ingest the PDF
        ingest = IngestDocument(
            document_repo=self._document_repo,
            file_storage=self._file_storage,
        )
        document, _ = await ingest.execute(IngestDocumentRequest(
            user_id=request.user_id,
            filename=request.filename,
            content=request.content,
            mime_type=request.mime_type,
            upload_date=request.upload_date,
            document_type=DocumentType.INVESTMENT_STATEMENT,
        ))
        logger.info("AttachTransfer: document ingested id=%s", document.id)

        # Step 3 — parse the PDF directly (no ExtractTransactions use case)
        file_bytes = await self._file_storage.read(Path(document.file_path))
        result = await self._llm_parser.parse(file_bytes, request.mime_type)
        logger.info("AttachTransfer: LLM returned %d transactions", len(result.transactions))

        # Step 4 — build and save transactions with document_id set correctly
        

        items: list[Transaction] = []
        for extracted in result.transactions:
            tx = Transaction.create(
                user_id=request.user_id,
                document_id=document.id,          # links to the N26 document
                date=extracted.date,
                description=extracted.description,
                amount=Decimal(str(extracted.amount)),
                transaction_type=TxType(extracted.transaction_type),
                category=TransactionCategory(extracted.category)
                    if extracted.category else TransactionCategory.OTHER,
                merchant=extracted.merchant,
            )
            items.append(tx)

        if items:
            saved = await self._transaction_repo.save_batch(items)
            logger.info("AttachTransfer: saved %d investment transactions", len(saved))

            # Verify immediately
            check = await self._transaction_repo.get_by_transfer_document(document.id)
            logger.info("AttachTransfer: verification found %d transactions in DB", len(check))
        else:
            logger.warning("AttachTransfer: no transactions extracted from PDF")

        # Step 5 — link document back to the transfer transaction
        transfer_tx.transfer_document_id = document.id
        await self._transaction_repo.save(transfer_tx)
        logger.info("AttachTransfer: linked document=%s to transfer tx=%s",
                    document.id, request.transfer_transaction_id)

        # Step 6 — mark document processed
        document.mark_processed()
        await self._document_repo.update(document)

        return {
            "account_name": request.account_name,
            "document_id": str(document.id),
            "transactions_extracted": len(items),
        }