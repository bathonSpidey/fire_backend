from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class DocumentType(StrEnum):
    BANK_STATEMENT = "bank_statement"
    INVESTMENT_STATEMENT = "investment_statement"
    RECEIPT = "receipt"
    UNKNOWN = "unknown"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


@dataclass
class Document:
    id: UUID
    user_id: UUID
    filename: str
    file_path: str
    document_type: DocumentType
    status: DocumentStatus
    uploaded_at: datetime
    file_hash: str = ""
    processed_at: datetime | None = None
    error_message: str | None = None

    @classmethod
    def create(
        cls,
        user_id: UUID,
        filename: str,
        file_path: str,
        file_hash: str,
        document_type: DocumentType = DocumentType.UNKNOWN,
    ) -> "Document":
        return cls(
            id=uuid4(),
            user_id=user_id,
            filename=filename,
            file_path=file_path,
            file_hash=file_hash,
            document_type=document_type,
            status=DocumentStatus.PENDING,
            uploaded_at=datetime.now(UTC),
        )

    def mark_processing(self) -> None:
        self.status = DocumentStatus.PROCESSING

    def mark_processed(self) -> None:
        self.status = DocumentStatus.PROCESSED
        self.processed_at = datetime.now(UTC)

    def mark_failed(self, reason: str) -> None:
        self.status = DocumentStatus.FAILED
        self.error_message = reason

    def is_duplicate_of(self, other_hash: str) -> bool:
        return bool(self.file_hash) and self.file_hash == other_hash