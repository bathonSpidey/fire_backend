import logging
from dataclasses import dataclass
from datetime import date as Date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fire.application.use_cases.ingest_document import IngestDocument, IngestDocumentRequest
from fire.domain.entities.document import DocumentType
from fire.domain.entities.transaction import (
    Transaction,
    TransactionCategory,
    TransactionType,
)
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
    Saves investment transactions directly — no ExtractTransactions use case
    so parent link is set before the first and only save.
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
        logger.info(
            "=== AttachTransfer START tx=%s account=%s ===",
            request.transfer_transaction_id,
            request.account_name,
        )

        transfer_tx = await self._transaction_repo.get_by_id(request.transfer_transaction_id)
        if transfer_tx is None:
            raise ValueError(f"Transaction not found: {request.transfer_transaction_id}")
        logger.info(
            "AttachTransfer: found transfer tx desc=%s amount=%s",
            transfer_tx.description,
            transfer_tx.amount,
        )

        # Step 1 — mark as TRANSFER
        transfer_tx.transaction_type = TransactionType.TRANSFER
        transfer_tx.transfer_account_name = request.account_name
        await self._transaction_repo.save(transfer_tx)
        logger.info("AttachTransfer: marked as TRANSFER to %s", request.account_name)

        # Step 2 — ingest PDF
        ingest = IngestDocument(
            document_repo=self._document_repo,
            file_storage=self._file_storage,
        )
        document, is_new = await ingest.execute(
            IngestDocumentRequest(
                user_id=request.user_id,
                filename=request.filename,
                content=request.content,
                mime_type=request.mime_type,
                upload_date=request.upload_date,
                document_type=DocumentType.INVESTMENT_STATEMENT,
            )
        )
        logger.info(
            "AttachTransfer: document id=%s is_new=%s path=%s",
            document.id,
            is_new,
            document.file_path,
        )

        # Step 3 — parse PDF
        file_bytes = await self._file_storage.read(Path(document.file_path))
        logger.info("AttachTransfer: read %d bytes from %s", len(file_bytes), document.file_path)

        # Always parse directly via PdfBankParserFactory for transfer statements —
        # this guarantees account_name hint reaches the bank-specific parser.
        from fire.infrastructure.llm.pdf_parsing.pdf_bank_parser_factory import PdfBankParserFactory

        result = PdfBankParserFactory().parse(file_bytes, account_name=request.account_name)
        logger.info(
            "AttachTransfer: parse result %d transactions institution=%s",
            len(result.transactions),
            result.account_institution,
        )
        logger.info(
            "AttachTransfer: LLM returned %d transactions raw_response_length=%d",
            len(result.transactions),
            len(result.raw_llm_response or ""),
        )

        if result.raw_llm_response:
            logger.info("AttachTransfer: raw response preview: %s", result.raw_llm_response[:300])

        if not result.transactions:
            logger.warning("AttachTransfer: LLM returned 0 transactions — nothing to save")
            # Still link the document so user can see it's attached
            transfer_tx.transfer_document_id = document.id
            await self._transaction_repo.save(transfer_tx)
            return {
                "account_name": request.account_name,
                "document_id": str(document.id),
                "transactions_extracted": 0,
            }

        # Step 4 — build entities with document_id set from the start
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
            )
            logger.info(
                "AttachTransfer: item[%d] id=%s desc=%s amount=%s date=%s doc=%s",
                i,
                tx.id,
                tx.description,
                tx.amount,
                tx.date,
                tx.document_id,
            )
            items.append(tx)

        # Step 5 — save all in one batch
        saved = await self._transaction_repo.save_batch(items)
        logger.info("AttachTransfer: save_batch saved %d items", len(saved))

        # Step 6 — verify persistence immediately
        check = await self._transaction_repo.get_by_transfer_document(document.id)
        logger.info(
            "AttachTransfer: verification query by document_id=%s found %d rows",
            document.id,
            len(check),
        )

        if len(check) == 0:
            logger.error(
                "AttachTransfer: ITEMS NOT PERSISTED — save_batch returned %d but DB has 0",
                len(saved),
            )

        # Step 7 — link document to transfer transaction
        transfer_tx.transfer_document_id = document.id
        await self._transaction_repo.save(transfer_tx)
        logger.info(
            "AttachTransfer: linked document=%s to transfer=%s", document.id, transfer_tx.id
        )

        # Step 8 — mark document processed
        document.mark_processed()
        await self._document_repo.update(document)

        logger.info("=== AttachTransfer DONE extracted=%d verified=%d ===", len(items), len(check))

        return {
            "account_name": request.account_name,
            "document_id": str(document.id),
            "transactions_extracted": len(saved),
        }
