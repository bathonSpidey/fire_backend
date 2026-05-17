from dataclasses import dataclass
from datetime import date as Date  # noqa: N812

from src.fire.domain.entities.document import Document, DocumentType
from src.fire.domain.interfaces.repositories import IDocumentRepository
from src.fire.domain.interfaces.services import IFileStorage


@dataclass
class IngestDocumentRequest:
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date
    document_type: DocumentType = DocumentType.UNKNOWN


class IngestDocument:
    """
    Use case: accept a raw uploaded file, deduplicate it, persist it,
    and return a Document entity ready for extraction.

    Single Responsibility: ingestion only — extraction is a separate use case.
    """

    def __init__(
        self,
        document_repo: IDocumentRepository,
        file_storage: IFileStorage,
    ) -> None:
        self._document_repo = document_repo
        self._file_storage = file_storage

    async def execute(self, request: IngestDocumentRequest) -> Document:
        file_hash = await self._file_storage.compute_hash(request.content)

        await self._reject_if_duplicate(file_hash)

        file_path = await self._file_storage.save(
            filename=request.filename,
            content=request.content,
            upload_date=request.upload_date,
        )

        document = Document.create(
            filename=request.filename,
            file_path=str(file_path),
            file_hash=file_hash,
            document_type=request.document_type,
        )

        return await self._document_repo.save(document)

    async def _reject_if_duplicate(self, file_hash: str) -> None:
        existing = await self._document_repo.get_by_hash(file_hash)
        if existing is not None:
            raise ValueError(f"duplicate: file already ingested as document {existing.id}")
