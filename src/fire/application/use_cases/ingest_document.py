from dataclasses import dataclass
from datetime import date as Date
from uuid import UUID

from fire.domain.entities.document import Document, DocumentType
from fire.domain.interfaces.repositories import IDocumentRepository
from fire.domain.interfaces.services import IFileStorage


@dataclass
class IngestDocumentRequest:
    user_id: UUID
    filename: str
    content: bytes
    mime_type: str
    upload_date: Date
    document_type: DocumentType = DocumentType.UNKNOWN


class IngestDocument:
    """
    Use case: accept a raw uploaded file, store it, and return a Document
    entity ready for extraction.

    If the same file (identical hash) was uploaded before, the existing
    document is returned as-is — no duplicate created, no error raised.
    This allows re-uploads without friction.
    """

    def __init__(
        self,
        document_repo: IDocumentRepository,
        file_storage: IFileStorage,
    ) -> None:
        self._document_repo = document_repo
        self._file_storage = file_storage

    async def execute(self, request: IngestDocumentRequest) -> tuple[Document, bool]:
        """
        Returns (document, is_new).
        is_new=False means this exact file was already ingested — caller
        can decide whether to re-extract or return the cached result.
        """
        file_hash = await self._file_storage.compute_hash(request.content)
        existing = await self._document_repo.get_by_hash(file_hash)

        if existing is not None:
            return existing, False

        file_path = await self._file_storage.save(
            filename=request.filename,
            content=request.content,
            upload_date=request.upload_date,
        )
        document = Document.create(
            user_id=request.user_id,
            filename=request.filename,
            file_path=str(file_path),
            file_hash=file_hash,
            document_type=request.document_type,
        )
        return await self._document_repo.save(document), True
