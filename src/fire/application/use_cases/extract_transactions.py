from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fire.domain.entities.document import DocumentStatus
from fire.domain.entities.transaction import Transaction
from fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser


@dataclass
class ExtractTransactionsRequest:
    document_id: UUID
    mime_type: str = "application/pdf"


class ExtractTransactions:
    """
    Use case: read a stored document, send to LLM parser,
    map results to Transaction entities, persist them.
    """

    def __init__(
        self,
        document_repo: IDocumentRepository,
        transaction_repo: ITransactionRepository,
        llm_parser: ILLMDocumentParser,
        file_storage: IFileStorage,
    ) -> None:
        self._document_repo = document_repo
        self._transaction_repo = transaction_repo
        self._llm_parser = llm_parser
        self._file_storage = file_storage

    async def execute(self, request: ExtractTransactionsRequest) -> list[Transaction]:
        document = await self._document_repo.get_by_id(request.document_id)
        if document is None:
            raise ValueError(f"Document not found: {request.document_id}")

        document.mark_processing()
        await self._document_repo.update(document)

        try:
            # Delete existing transactions for this document before re-extracting
            # Uses delete_by_document (no cascade) to avoid destroying linked investment/receipt data
            deleted = await self._transaction_repo.delete_by_document(document.id)
            if deleted:
                import logging as _l

                _l.getLogger(__name__).info(
                    "ExtractTransactions: cleared %d existing transactions", deleted
                )

            file_bytes = await self._file_storage.read(Path(document.file_path))
            extraction = await self._llm_parser.parse(file_bytes, request.mime_type)
            transactions = [
                Transaction.create(
                    user_id=document.user_id,
                    document_id=document.id,
                    date=extracted.date,
                    description=extracted.description,
                    amount=extracted.amount,
                    transaction_type=extracted.transaction_type,
                    category=extracted.category,
                    merchant=extracted.merchant,
                )
                for extracted in extraction.transactions
            ]
            saved = await self._transaction_repo.save_batch(transactions)
            # Persist closing balance if extracted
            import logging as _log

            _logger = _log.getLogger(__name__)
            _logger.info(
                "ExtractTransactions: closing_balance=%s statement_date=%s institution=%s",
                extraction.closing_balance,
                extraction.statement_period_end,
                extraction.account_institution,
            )
            if extraction.closing_balance is not None:
                document.closing_balance = extraction.closing_balance
            if extraction.statement_period_end is not None:
                document.statement_date = extraction.statement_period_end
            if extraction.account_institution:
                document.account_name = extraction.account_institution
            document.mark_processed()
            await self._document_repo.update(document)
            _logger.info(
                "ExtractTransactions: document saved with closing_balance=%s",
                document.closing_balance,
            )
            return saved

        except Exception as exc:
            document.mark_failed(str(exc))
            await self._document_repo.update(document)
            raise
