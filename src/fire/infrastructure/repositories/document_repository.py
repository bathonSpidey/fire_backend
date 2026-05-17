from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from src.fire.domain.entities.document import Document, DocumentStatus, DocumentType
from src.fire.domain.interfaces.repositories import IDocumentRepository
from src.fire.infrastructure.db.models import DocumentORM


class DocumentRepository(IDocumentRepository):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    async def save(self, document: Document) -> Document:
        with self._session_factory() as session:
            session.merge(_to_orm(document))
            session.commit()
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        with self._session_factory() as session:
            orm = session.get(DocumentORM, str(document_id))
            return _to_entity(orm) if orm else None

    async def get_by_hash(self, file_hash: str) -> Document | None:
        with self._session_factory() as session:
            orm = session.query(DocumentORM).filter_by(file_hash=file_hash).first()
            return _to_entity(orm) if orm else None

    async def list_by_user(self, user_id: UUID, limit: int = 50, offset: int = 0) -> list[Document]:
        with self._session_factory() as session:
            rows = (
                session.query(DocumentORM)
                .filter_by(user_id=str(user_id))
                .order_by(DocumentORM.uploaded_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [_to_entity(r) for r in rows]

    async def update(self, document: Document) -> Document:
        with self._session_factory() as session:
            session.merge(_to_orm(document))
            session.commit()
        return document


def _to_orm(doc: Document) -> DocumentORM:
    return DocumentORM(
        id=str(doc.id),
        user_id=str(doc.user_id),
        filename=doc.filename,
        file_path=doc.file_path,
        file_hash=doc.file_hash,
        document_type=doc.document_type.value,
        status=doc.status.value,
        uploaded_at=doc.uploaded_at,
        processed_at=doc.processed_at,
        error_message=doc.error_message,
    )


def _to_entity(orm: DocumentORM) -> Document:
    return Document(
        id=UUID(orm.id),
        user_id=UUID(orm.user_id),
        filename=orm.filename,
        file_path=orm.file_path,
        file_hash=orm.file_hash,
        document_type=DocumentType(orm.document_type),
        status=DocumentStatus(orm.status),
        uploaded_at=orm.uploaded_at,
        processed_at=orm.processed_at,
        error_message=orm.error_message,
    )