from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from src.fire.domain.entities.transaction import Transaction
from src.fire.domain.interfaces.repositories import IDocumentRepository, ITransactionRepository
from src.fire.domain.interfaces.services import IFileStorage, ILLMDocumentParser


@dataclass
class ExtractTransactionsRequest:
    document_id: UUID
    mime_type: str = "application/pdf"


class ExtractTransactions:
    """
    Use case: read a stored document file, send to LLM parser,
    map results to Transaction entities, persist them, and mark
    the Document as processed (or failed).

    Single Responsibility: extraction only — ingestion and insights are separate.
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
            file_bytes = await self._file_storage.read(Path(document.file_path))
            extraction = await self._llm_parser.parse(file_bytes, request.mime_type)
            transactions = [
                Transaction.create(
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
            document.mark_processed()
            await self._document_repo.update(document)
            return saved

        except Exception as exc:
            document.mark_failed(str(exc))
            await self._document_repo.update(document)
            raise
