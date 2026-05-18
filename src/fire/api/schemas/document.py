from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.fire.domain.entities.document import DocumentStatus, DocumentType


class DocumentResponse(BaseModel):
    id: UUID
    user_id: UUID
    filename: str
    document_type: DocumentType
    status: DocumentStatus
    uploaded_at: datetime
    processed_at: datetime | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    document: DocumentResponse
    transactions_extracted: int